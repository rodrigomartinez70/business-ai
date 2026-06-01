"""
Agente de P&L Mensual.

Estado de resultados completo: ingresos por departamento, gastos clasificados,
GOP, margen operativo y métricas hoteleras (ocupación, ADR, RevPAR).
Comparativa contra mes anterior y mismo mes del año pasado.
Sin LLM — SQL puro.
"""

import calendar
import logging
from datetime import date

from .... import config
from ....agents._common import fmt_moneda, to_float, var_pct, var_txt

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Helpers de fecha
# ─────────────────────────────────────────────────────────────

def _mes_rango(año: int, mes: int) -> tuple[date, date]:
    ultimo_dia = calendar.monthrange(año, mes)[1]
    return date(año, mes, 1), date(año, mes, ultimo_dia)


def _mes_anterior(año: int, mes: int) -> tuple[int, int]:
    return (año - 1, 12) if mes == 1 else (año, mes - 1)


# ─────────────────────────────────────────────────────────────
# Cálculo de métricas para un período
# ─────────────────────────────────────────────────────────────

async def _metricas_mes(conn, fi: date, ff: date) -> dict:
    """Calcula todas las métricas P&L para el rango fi→ff (un mes completo)."""
    dias = (ff - fi).days + 1

    hab_activas = await conn.fetchval(
        "SELECT COUNT(*) FROM habitaciones WHERE activa = TRUE"
    )
    cap_noches = int(hab_activas or 0) * dias   # capacidad total del período

    # ── Ingresos hospedaje (devengado: checkouts en el período) ──────────
    hosp = dict(await conn.fetchrow("""
        SELECT
            COALESCE(SUM(r.total_hospedaje), 0) AS ingresos,
            COALESCE(SUM(r.noches), 0)          AS noches_vendidas
        FROM reservas r
        WHERE r.fecha_salida BETWEEN $1 AND $2
          AND r.estado = 'checkout'
    """, fi, ff))

    # ── Frigobar ─────────────────────────────────────────────────────────
    frig = dict(await conn.fetchrow("""
        SELECT
            COALESCE(SUM(total),       0) AS ingresos,
            COALESCE(SUM(costo_total), 0) AS costos,
            COALESCE(SUM(margen),      0) AS margen
        FROM consumos_frigobar
        WHERE fecha BETWEEN $1 AND $2
    """, fi, ff))

    # ── Servicios ────────────────────────────────────────────────────────
    serv = dict(await conn.fetchrow("""
        SELECT
            COALESCE(SUM(total),       0) AS ingresos,
            COALESCE(SUM(costo_total), 0) AS costos,
            COALESCE(SUM(margen),      0) AS margen
        FROM consumos_servicios
        WHERE fecha BETWEEN $1 AND $2
    """, fi, ff))

    # ── Cobros reales del período (base caja) ─────────────────────────────
    cobros = await conn.fetchval("""
        SELECT COALESCE(SUM(monto), 0)
        FROM pagos
        WHERE fecha BETWEEN $1 AND $2 AND estado = 'pagado'
    """, fi, ff)

    # ── Comisiones OTA devengadas (checkouts del período) ─────────────────
    comisiones_ota = await conn.fetchval("""
        SELECT COALESCE(
            ROUND(SUM(r.total_hospedaje * cv.comision_pct / 100), 0), 0
        )
        FROM reservas r
        JOIN canales_venta cv ON cv.id = r.canal_id
        WHERE r.fecha_salida BETWEEN $1 AND $2
          AND r.estado = 'checkout'
          AND cv.comision_pct > 0
    """, fi, ff)

    # ── Gastos por categoría ──────────────────────────────────────────────
    gastos_cat = [dict(r) for r in await conn.fetch("""
        SELECT
            COALESCE(cg.nombre, 'Sin categoría') AS categoria,
            SUM(g.monto)                          AS monto
        FROM gastos g
        LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
        WHERE g.fecha BETWEEN $1 AND $2
        GROUP BY cg.nombre
        ORDER BY monto DESC
    """, fi, ff)]

    # ── Cálculos derivados ────────────────────────────────────────────────
    _f = to_float

    ing_hosp   = _f(hosp["ingresos"])
    ing_frig   = _f(frig["ingresos"])
    ing_serv   = _f(serv["ingresos"])
    total_ing  = ing_hosp + ing_frig + ing_serv

    comis_ota  = _f(comisiones_ota)
    total_gast = sum(_f(c["monto"]) for c in gastos_cat)
    # GOP neto: descuenta comisiones OTA del lado de ingresos
    ing_neto   = total_ing - comis_ota
    gop        = ing_neto - total_gast
    margen_gop = round(gop * 100 / ing_neto, 1) if ing_neto > 0 else None

    noches_vend = int(hosp["noches_vendidas"] or 0)
    ocupacion   = round(noches_vend * 100 / cap_noches, 1) if cap_noches > 0 else None
    adr         = round(ing_hosp / noches_vend, 2) if noches_vend > 0 else None
    revpar      = round(ing_hosp / cap_noches, 2)  if cap_noches > 0 else None

    margen_frig = round(_f(frig["margen"]) * 100 / ing_frig, 1) if ing_frig > 0 else None
    margen_serv = round(_f(serv["margen"]) * 100 / ing_serv, 1) if ing_serv > 0 else None

    return {
        "periodo":  {"inicio": str(fi), "fin": str(ff), "dias": dias},
        "ingresos": {
            "hospedaje":    ing_hosp,
            "comisiones_ota": comis_ota,
            "neto":         ing_neto,
            "frigobar":  ing_frig,
            "servicios": ing_serv,
            "total":     total_ing,
            "cobros_caja": _f(cobros),
        },
        "departamentos": {
            "frigobar": {
                "ingresos": ing_frig,
                "costos":   _f(frig["costos"]),
                "margen":   _f(frig["margen"]),
                "margen_pct": margen_frig,
            },
            "servicios": {
                "ingresos": ing_serv,
                "costos":   _f(serv["costos"]),
                "margen":   _f(serv["margen"]),
                "margen_pct": margen_serv,
            },
        },
        "gastos": {
            "total":         total_gast,
            "por_categoria": [
                {"categoria": r["categoria"], "monto": _f(r["monto"])}
                for r in gastos_cat
            ],
        },
        "resultado": {
            "gop":        gop,
            "margen_pct": margen_gop,
            "estado":     "positivo" if gop >= 0 else "negativo",
        },
        "metricas": {
            "noches_vendidas": noches_vend,
            "cap_noches":      cap_noches,
            "hab_activas":     int(hab_activas or 0),
            "ocupacion_pct":   ocupacion,
            "adr":             adr,
            "revpar":          revpar,
        },
    }


# ─────────────────────────────────────────────────────────────
# Punto de entrada principal
# ─────────────────────────────────────────────────────────────

async def calcular_pnl(año: int, mes: int) -> dict:
    from datetime import timedelta

    fi, ff_mes = _mes_rango(año, mes)

    # Si el mes aún no cerró, capear al día de ayer para no incluir días sin datos.
    # Los períodos de referencia usan exactamente los mismos N días desde su día 1,
    # garantizando comparaciones equivalentes (MoM y YoY comparables).
    hoy = date.today()
    ff  = min(ff_mes, hoy - timedelta(days=1)) if ff_mes >= hoy else ff_mes
    if ff < fi:
        ff = fi   # guardia por si el mes empieza hoy
    dias = (ff - fi).days + 1   # días efectivos del período actual

    año_ant, mes_ant = _mes_anterior(año, mes)
    fi_ant  = date(año_ant, mes_ant, 1)
    ff_ant  = fi_ant + timedelta(days=dias - 1)     # mismos N días

    fi_aa   = date(año - 1, mes, 1)
    ff_aa   = fi_aa + timedelta(days=dias - 1)      # mismos N días

    async with config.db_pool.acquire() as conn:
        actual    = await _metricas_mes(conn, fi,     ff)
        anterior  = await _metricas_mes(conn, fi_ant, ff_ant)
        año_pasado= await _metricas_mes(conn, fi_aa,  ff_aa)

    _var = var_pct

    def _comp(campo, sub=None):
        a = actual[campo]    if sub is None else actual[campo][sub]
        p = anterior[campo]  if sub is None else anterior[campo][sub]
        y = año_pasado[campo]if sub is None else año_pasado[campo][sub]
        return {
            "vs_mes_anterior":  _var(a, p),
            "vs_año_anterior":  _var(a, y),
        }

    mes_nombre = fi.strftime("%B %Y").capitalize()
    parcial    = ff < ff_mes   # True si el mes no cerró completamente

    return {
        "mes":        mes,
        "año":        año,
        "mes_nombre": mes_nombre,
        "parcial":    parcial,
        "dias_comparados": dias,
        "actual":     actual,
        "anterior":   anterior,
        "año_pasado": año_pasado,
        "comparativas": {
            "ingresos_total": _comp("ingresos", "total"),
            "gop":            {
                "vs_mes_anterior": _var(actual["resultado"]["gop"], anterior["resultado"]["gop"]),
                "vs_año_anterior": _var(actual["resultado"]["gop"], año_pasado["resultado"]["gop"]),
            },
            "ocupacion": {
                "vs_mes_anterior": _var(
                    actual["metricas"]["ocupacion_pct"],
                    anterior["metricas"]["ocupacion_pct"],
                ),
                "vs_año_anterior": _var(
                    actual["metricas"]["ocupacion_pct"],
                    año_pasado["metricas"]["ocupacion_pct"],
                ),
            },
            "revpar": {
                "vs_mes_anterior": _var(actual["metricas"]["revpar"], anterior["metricas"]["revpar"]),
                "vs_año_anterior": _var(actual["metricas"]["revpar"], año_pasado["metricas"]["revpar"]),
            },
        },
    }


async def calcular_pnl_ytd(hasta: date) -> dict:
    """
    P&L acumulado del año (Year-To-Date): 1-ene → `hasta`, comparado contra
    el mismo período del año anterior (1-ene → misma fecha del año pasado).

    Devuelve la misma estructura que calcular_pnl pero con comparativa solo
    contra el año anterior (vs_mes_anterior = None), compatible con el
    renderizado y con generar_insights.
    """
    from datetime import timedelta

    fi = date(hasta.year, 1, 1)
    ff = hasta

    # Mismo período del año anterior. Cubre el borde 29-feb cayendo a 28.
    fi_aa = date(hasta.year - 1, 1, 1)
    try:
        ff_aa = date(hasta.year - 1, hasta.month, hasta.day)
    except ValueError:
        ff_aa = date(hasta.year - 1, hasta.month, 28)

    async with config.db_pool.acquire() as conn:
        actual     = await _metricas_mes(conn, fi,    ff)
        año_pasado = await _metricas_mes(conn, fi_aa, ff_aa)

    _var = var_pct

    def _comp_aa(a_val, y_val):
        return {"vs_mes_anterior": None, "vs_año_anterior": _var(a_val, y_val)}

    return {
        "mes":        None,
        "año":        hasta.year,
        "mes_nombre": f"YTD {hasta.year} (al {ff.strftime('%d/%m')})",
        "parcial":    True,
        "dias_comparados": (ff - fi).days + 1,
        "actual":     actual,
        "anterior":   None,
        "año_pasado": año_pasado,
        "periodo":    {"inicio": str(fi),    "fin": str(ff)},
        "ref_anterior": {"inicio": str(fi_aa), "fin": str(ff_aa)},
        "comparativas": {
            "ingresos_total": _comp_aa(actual["ingresos"]["total"],       año_pasado["ingresos"]["total"]),
            "gop":            _comp_aa(actual["resultado"]["gop"],         año_pasado["resultado"]["gop"]),
            "ocupacion":      _comp_aa(actual["metricas"]["ocupacion_pct"],año_pasado["metricas"]["ocupacion_pct"]),
            "revpar":         _comp_aa(actual["metricas"]["revpar"],       año_pasado["metricas"]["revpar"]),
        },
    }


# ─────────────────────────────────────────────────────────────
# Renderizado
# ─────────────────────────────────────────────────────────────

_var_txt = var_txt


def renderizar_pnl_markdown(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)
    a   = data["actual"]
    ant = data["anterior"]
    ay  = data["año_pasado"]
    c   = data["comparativas"]

    ing  = a["ingresos"]
    gas  = a["gastos"]
    res  = a["resultado"]
    met  = a["metricas"]

    nota_parcial = (
        f" *(parcial — primeros {data['dias_comparados']} días, "
        f"referencias también {data['dias_comparados']}d desde el 1)*"
        if data["parcial"] else ""
    )
    lines = [
        f"# 📑 P&L Mensual — {biz}",
        f"**Período:** {data['mes_nombre']}{nota_parcial}",
        f"**Habitaciones activas:** {met['hab_activas']}",
        "",
        "---",
        "",
        "## 💰 Ingresos",
        "| Departamento | Monto | % del total |",
        "|---|---|---|",
    ]
    total = ing["total"] or 1
    lines += [
        f"| Hospedaje | {fm(ing['hospedaje'])} | {ing['hospedaje']*100/total:.1f}% |",
        f"| Frigobar | {fm(ing['frigobar'])} | {ing['frigobar']*100/total:.1f}% |",
        f"| Servicios | {fm(ing['servicios'])} | {ing['servicios']*100/total:.1f}% |",
        f"| **Total ingresos** | **{fm(ing['total'])}** | 100% |",
        f"| *Cobros caja* | *{fm(ing['cobros_caja'])}* | — |",
    ]

    dep = a["departamentos"]
    if dep["frigobar"]["ingresos"] > 0 or dep["servicios"]["ingresos"] > 0:
        lines += [
            "", "### Márgenes departamentales",
            "| Depto | Ingresos | Costos | Margen | % |",
            "|---|---|---|---|---|",
        ]
        for nombre, d in dep.items():
            if d["ingresos"] > 0:
                pct = f"{d['margen_pct']:.1f}%" if d["margen_pct"] is not None else "—"
                lines.append(
                    f"| {nombre.capitalize()} | {fm(d['ingresos'])} | "
                    f"{fm(d['costos'])} | {fm(d['margen'])} | {pct} |"
                )

    lines += ["", "---", "", "## 📋 Gastos Operativos",
              "| Categoría | Monto | % ingresos |",
              "|---|---|---|"]
    for g in gas["por_categoria"]:
        pct = f"{g['monto']*100/ing['total']:.1f}%" if ing["total"] > 0 else "—"
        lines.append(f"| {g['categoria']} | {fm(g['monto'])} | {pct} |")
    lines.append(f"| **Total gastos** | **{fm(gas['total'])}** | "
                 f"{gas['total']*100/ing['total']:.1f}% |" if ing["total"] > 0 else
                 f"| **Total gastos** | **{fm(gas['total'])}** | — |")

    gop_icono = "✅" if res["estado"] == "positivo" else "🔴"
    lines += [
        "", "---", "", "## 📈 Resultado Operativo (GOP)",
        "| | Actual | Mes anterior | Año anterior |",
        "|---|---|---|---|",
        f"| GOP | **{fm(res['gop'])}** | {fm(ant['resultado']['gop'])} | {fm(ay['resultado']['gop'])} |",
        f"| Margen GOP | **{res['margen_pct'] or 0:.1f}%** | {ant['resultado']['margen_pct'] or 0:.1f}% | {ay['resultado']['margen_pct'] or 0:.1f}% |",
        f"| Variación | — | {_var_txt(c['gop']['vs_mes_anterior'])} | {_var_txt(c['gop']['vs_año_anterior'])} |",
        f"",
        f"{gop_icono} **GOP: {fm(res['gop'])}** "
        f"({_var_txt(c['gop']['vs_mes_anterior'])} vs mes ant · "
        f"{_var_txt(c['gop']['vs_año_anterior'])} vs año ant)",
    ]

    lines += [
        "", "---", "", "## 🏨 Métricas Hoteleras",
        "| Métrica | Actual | Mes anterior | Año anterior |",
        "|---|---|---|---|",
        f"| Ocupación | **{met['ocupacion_pct'] or 0:.1f}%** | {ant['metricas']['ocupacion_pct'] or 0:.1f}% | {ay['metricas']['ocupacion_pct'] or 0:.1f}% |",
        f"| ADR | **{fm(met['adr'] or 0)}** | {fm(ant['metricas']['adr'] or 0)} | {fm(ay['metricas']['adr'] or 0)} |",
        f"| RevPAR | **{fm(met['revpar'] or 0)}** | {fm(ant['metricas']['revpar'] or 0)} | {fm(ay['metricas']['revpar'] or 0)} |",
        f"| Noches vendidas | **{met['noches_vendidas']}** | {ant['metricas']['noches_vendidas']} | {ay['metricas']['noches_vendidas']} |",
    ]

    return "\n".join(lines)

