"""
Agente de Rentabilidad por Canal.

Calcula ingresos brutos, comisiones, ingresos netos, tasa de cancelación
y ADR por canal de venta. Compara con el período anterior y genera un
ranking por rentabilidad real.
Sin LLM — SQL puro.
"""

import calendar
import logging
from datetime import date, timedelta

from .. import config
from ._common import COLOR, fmt_moneda, to_float, var_pct, var_txt

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Cálculo por período
# ─────────────────────────────────────────────────────────────

async def _metricas_canales(conn, fi: date, ff: date) -> list[dict]:
    rows = [dict(r) for r in await conn.fetch("""
        SELECT
            cv.nombre                                                              AS canal,
            cv.comision_pct,
            COUNT(r.id)                                                           AS total_reservas,
            COUNT(r.id) FILTER (WHERE r.estado NOT IN ('cancelada','no_show'))    AS reservas_ok,
            COUNT(r.id) FILTER (WHERE r.estado IN ('cancelada','no_show'))        AS canceladas,
            ROUND(
                COUNT(r.id) FILTER (WHERE r.estado IN ('cancelada','no_show'))
                * 100.0 / NULLIF(COUNT(r.id), 0), 1
            )                                                                     AS tasa_cancel_pct,
            COALESCE(SUM(r.total_hospedaje)
                FILTER (WHERE r.estado = 'checkout'),                             0) AS hosp_bruto,
            COALESCE(SUM(cf.total),                                               0) AS frigobar,
            COALESCE(SUM(cs.total),                                               0) AS servicios,
            COALESCE(ROUND(SUM(r.total_hospedaje * cv.comision_pct / 100)
                FILTER (WHERE r.estado = 'checkout'), 0),                         0) AS comision,
            COALESCE(ROUND(
                (SUM(r.total_hospedaje) FILTER (WHERE r.estado = 'checkout')
                 + COALESCE(SUM(cf.total), 0) + COALESCE(SUM(cs.total), 0))
                * (1 - cv.comision_pct / 100)
            , 0),                                                                  0) AS ingresos_netos,
            COALESCE(ROUND(SUM(r.tarifa_noche * r.noches)
                / NULLIF(SUM(r.noches) FILTER (WHERE r.estado = 'checkout'), 0), 0), 0) AS adr,
            COALESCE(SUM(r.noches)
                FILTER (WHERE r.estado = 'checkout'),                             0) AS noches_vendidas
        FROM canales_venta cv
        LEFT JOIN reservas r ON r.canal_id = cv.id
            AND r.fecha_salida BETWEEN $1 AND $2
        LEFT JOIN consumos_frigobar cf ON cf.reserva_id = r.id
            AND cf.fecha BETWEEN $1 AND $2
        LEFT JOIN consumos_servicios cs ON cs.reserva_id = r.id
            AND cs.fecha BETWEEN $1 AND $2
        WHERE cv.activo = TRUE
        GROUP BY cv.id, cv.nombre, cv.comision_pct
        ORDER BY ingresos_netos DESC
    """, fi, ff)]

    _f = to_float

    total_neto = sum(_f(r["ingresos_netos"]) for r in rows) or 1

    return [
        {
            "canal":            r["canal"],
            "comision_pct":     _f(r["comision_pct"]),
            "total_reservas":   int(r["total_reservas"] or 0),
            "reservas_ok":      int(r["reservas_ok"] or 0),
            "canceladas":       int(r["canceladas"] or 0),
            "tasa_cancel_pct":  _f(r["tasa_cancel_pct"]),
            "ingresos_brutos":  _f(r["hosp_bruto"]) + _f(r["frigobar"]) + _f(r["servicios"]),
            "hospedaje":        _f(r["hosp_bruto"]),
            "frigobar":         _f(r["frigobar"]),
            "servicios":        _f(r["servicios"]),
            "comision":         _f(r["comision"]),
            "ingresos_netos":   _f(r["ingresos_netos"]),
            "adr":              _f(r["adr"]),
            "noches_vendidas":  int(r["noches_vendidas"] or 0),
            "mix_pct":          round(_f(r["ingresos_netos"]) * 100 / total_neto, 1),
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────
# Punto de entrada principal
# ─────────────────────────────────────────────────────────────

async def calcular_rentabilidad_canal(año: int, mes: int, hasta: date | None = None) -> dict:
    """
    Rentabilidad por canal del mes (año, mes).

    Si `hasta` se pasa, recorta el período actual a esa fecha (p.ej. el domingo
    anterior, para un acumulado mes-en-curso). Si no, recorta al día de ayer.
    El período de referencia (mismo mes del año anterior) usa los mismos N días.
    """
    ultimo_dia = calendar.monthrange(año, mes)[1]
    fi   = date(año, mes, 1)
    ff   = date(año, mes, ultimo_dia)

    # Período de referencia: mismo mes del año anterior
    fi_ant = date(año - 1, mes, 1)
    ff_ant = date(año - 1, mes, calendar.monthrange(año - 1, mes)[1])

    # Corte: fecha explícita o el día de ayer si el mes no cerró
    corte    = hasta if hasta is not None else (date.today() - timedelta(days=1))
    ff_ef    = min(ff, corte)
    dias_ef  = (ff_ef - fi).days + 1
    ff_ef_ant = fi_ant + timedelta(days=dias_ef - 1)

    async with config.db_pool.acquire() as conn:
        actual   = await _metricas_canales(conn, fi,     ff_ef)
        anterior = await _metricas_canales(conn, fi_ant, ff_ef_ant)

    # Índice anterior por canal para variaciones
    ant_idx = {c["canal"]: c for c in anterior}

    _var = var_pct

    canales_con_var = []
    for c in actual:
        p = ant_idx.get(c["canal"], {})
        canales_con_var.append({
            **c,
            "vs_año_anterior": {
                "ingresos_netos":  _var(c["ingresos_netos"],  p.get("ingresos_netos", 0)),
                "reservas_ok":     _var(c["reservas_ok"],     p.get("reservas_ok", 0)),
                "adr":             _var(c["adr"],              p.get("adr", 0)),
                "tasa_cancel_pct": _var(c["tasa_cancel_pct"], p.get("tasa_cancel_pct", 0)),
            },
        })

    # Totales
    total_brutos = sum(c["ingresos_brutos"] for c in actual)
    total_comis  = sum(c["comision"]        for c in actual)
    total_netos  = sum(c["ingresos_netos"]  for c in actual)
    total_res    = sum(c["reservas_ok"]     for c in actual)
    total_cancel = sum(c["canceladas"]      for c in actual)

    # Canal más rentable (mayor ingreso neto con ≥1 reserva)
    canal_top = next(
        (c["canal"] for c in canales_con_var if c["ingresos_netos"] > 0),
        None
    )
    # Canal con menor tasa de cancelación (con ≥1 reserva)
    canal_confiable = min(
        (c for c in canales_con_var if c["total_reservas"] > 0),
        key=lambda c: c["tasa_cancel_pct"],
        default=None,
    )

    mes_nombre = fi.strftime("%B %Y").capitalize()
    parcial    = ff_ef < ff

    return {
        "mes":        mes,
        "año":        año,
        "mes_nombre": mes_nombre,
        "parcial":    parcial,
        "dias_comparados": dias_ef,
        "periodo":    {"inicio": str(fi), "fin": str(ff_ef)},
        "ref_anterior":{"inicio": str(fi_ant), "fin": str(ff_ef_ant)},
        "canales":    canales_con_var,
        "totales": {
            "ingresos_brutos": total_brutos,
            "comisiones":      total_comis,
            "ingresos_netos":  total_netos,
            "reservas":        total_res,
            "canceladas":      total_cancel,
            "tasa_cancel_pct": round(total_cancel * 100 / (total_res + total_cancel), 1)
                               if (total_res + total_cancel) > 0 else 0,
        },
        "insights": {
            "canal_mas_rentable":  canal_top,
            "canal_mas_confiable": canal_confiable["canal"] if canal_confiable else None,
        },
    }


# ─────────────────────────────────────────────────────────────
# Renderizado
# ─────────────────────────────────────────────────────────────

_var_txt = var_txt


def renderizar_rentabilidad_canal_markdown(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)
    t   = data["totales"]
    ins = data["insights"]

    nota = f" *(primeros {data['dias_comparados']}d)*" if data["parcial"] else ""

    lines = [
        f"## 🏪 Rentabilidad por Canal — {biz}",
        f"**Período:** {data['mes_nombre']}{nota}",
        f"**Referencia:** {data['ref_anterior']['inicio'][:7]}",
        "",
        "### Totales",
        "| | Monto |",
        "|---|---|",
        f"| Ingresos brutos | {fm(t['ingresos_brutos'])} |",
        f"| Comisiones OTA  | {fm(t['comisiones'])} |",
        f"| **Ingresos netos** | **{fm(t['ingresos_netos'])}** |",
        f"| Reservas OK     | {t['reservas']} |",
        f"| Cancelaciones   | {t['canceladas']} ({t['tasa_cancel_pct']:.1f}%) |",
        "",
        "### Ranking por canal",
        "| Canal | Reservas | Neto | Mix | Comisión | Cancel. | ADR | vs año ant. |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in data["canales"]:
        var = _var_txt(c["vs_año_anterior"]["ingresos_netos"])
        lines.append(
            f"| {c['canal']} | {c['reservas_ok']} | {fm(c['ingresos_netos'])} "
            f"| {c['mix_pct']:.1f}% | {c['comision_pct']:.0f}% "
            f"| {c['tasa_cancel_pct']:.1f}% | {fm(c['adr'])} | {var} |"
        )

    if ins["canal_mas_rentable"] or ins["canal_mas_confiable"]:
        lines += ["", "### 💡 Insights"]
        if ins["canal_mas_rentable"]:
            lines.append(f"- **Canal más rentable:** {ins['canal_mas_rentable']}")
        if ins["canal_mas_confiable"]:
            lines.append(f"- **Canal más confiable (menor cancelación):** {ins['canal_mas_confiable']}")

    return "\n".join(lines)


def build_discord_embed_rentabilidad_canal(data: dict, cfg: dict) -> dict:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)
    t   = data["totales"]
    ins = data["insights"]

    # Color según tasa de cancelación global
    tasa = t["tasa_cancel_pct"]
    color = COLOR.OK if tasa < 10 else (COLOR.ALERTA if tasa < 20 else COLOR.CRITICO)

    # Tabla de canales compacta
    canales_lines = []
    for i, c in enumerate(data["canales"], 1):
        var = _var_txt(c["vs_año_anterior"]["ingresos_netos"])
        canales_lines.append(
            f"**{i}. {c['canal']}** — {fm(c['ingresos_netos'])} neto "
            f"({c['mix_pct']:.0f}% mix) · cancel. {c['tasa_cancel_pct']:.1f}% · {var}"
        )
    canales_txt = "\n".join(canales_lines) or "—"

    nota = f" · {data['dias_comparados']}d" if data["parcial"] else ""

    fields = [
        {
            "name":   "💰 Totales del período",
            "value":  (
                f"Brutos: {fm(t['ingresos_brutos'])}\n"
                f"Comisiones: {fm(t['comisiones'])}\n"
                f"**Netos: {fm(t['ingresos_netos'])}**\n"
                f"Reservas: {t['reservas']} · Cancel.: {t['canceladas']} ({t['tasa_cancel_pct']:.1f}%)"
            ),
            "inline": True,
        },
        {
            "name":   "💡 Insights",
            "value":  (
                f"🏆 Más rentable: **{ins['canal_mas_rentable'] or '—'}**\n"
                f"✅ Más confiable: **{ins['canal_mas_confiable'] or '—'}**"
            ),
            "inline": True,
        },
        {
            "name":   "📊 Ranking por ingreso neto",
            "value":  canales_txt,
            "inline": False,
        },
    ]

    return {
        "embeds": [{
            "title":  f"🏪 Rentabilidad por Canal — {biz} · {data['mes_nombre']}{nota}",
            "color":  color,
            "fields": fields,
        }]
    }
