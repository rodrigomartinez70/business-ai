"""
Agente de Revenue Management.

Monitorea ocupación actual, ADR y RevPAR.
Proyecta los próximos 30 días y detecta oportunidades de precio
(días con alta demanda pero tarifa por debajo del promedio histórico).
Sin LLM — SQL puro.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from .. import config

logger = logging.getLogger(__name__)

# Umbrales de oportunidad de precio
OCUPACION_ALTA_PCT   = 60    # días con ≥60% de ocupación se consideran "alta demanda"
DESCUENTO_UMBRAL_PCT = 10    # si el ADR proyectado está ≥10% por debajo del histórico → oportunidad


async def calcular_revenue_management(horizon_dias: int = 30) -> dict:
    hoy = date.today()

    async with config.db_pool.acquire() as conn:

        # ── Capacidad total ──────────────────────────────────────────────
        hab_activas = int(await conn.fetchval(
            "SELECT COUNT(*) FROM habitaciones WHERE activa = TRUE"
        ) or 0)

        # ── Snapshot hoy ────────────────────────────────────────────────
        snapshot = dict(await conn.fetchrow("""
            SELECT
                COUNT(*)                                                   AS ocupadas,
                ROUND(SUM(r.tarifa_noche * r.noches)
                      / NULLIF(SUM(r.noches), 0), 0)                      AS adr,
                COUNT(*) FILTER (WHERE r.fecha_entrada = CURRENT_DATE)    AS checkins_hoy
            FROM reservas r
            WHERE r.estado = 'checkin'
        """))

        # ── ADR histórico de referencia (últimos 30 días de checkout) ────
        adr_historico = await conn.fetchval("""
            SELECT ROUND(SUM(tarifa_noche * noches) / NULLIF(SUM(noches), 0), 0)
            FROM reservas
            WHERE fecha_salida BETWEEN CURRENT_DATE - 30 AND CURRENT_DATE
              AND estado = 'checkout'
        """)
        adr_ref = float(adr_historico or 0)

        # ── Tarifa rack promedio (techo de referencia) ───────────────────
        tarifa_rack = float(await conn.fetchval(
            "SELECT ROUND(AVG(tarifa_base), 0) FROM habitaciones WHERE activa = TRUE"
        ) or 0)

        # ── Ocupación y ADR proyectados día a día (horizon_dias días) ───
        calendar_rows = [dict(r) for r in await conn.fetch("""
            SELECT
                d.fecha,
                COUNT(r.id)                           AS reservas,
                ROUND(COUNT(r.id) * 100.0 / $1, 1)                        AS ocupacion_pct,
                ROUND(SUM(r.tarifa_noche * r.noches)
                      / NULLIF(SUM(r.noches), 0), 0)                     AS adr
            FROM (
                SELECT generate_series(
                    CURRENT_DATE,
                    CURRENT_DATE + ($2 - 1),
                    interval '1 day'
                )::date AS fecha
            ) d
            LEFT JOIN reservas r
                ON  d.fecha >= r.fecha_entrada
                AND d.fecha <  r.fecha_salida
                AND r.estado IN ('confirmada', 'checkin')
            GROUP BY d.fecha
            ORDER BY d.fecha
        """, hab_activas, horizon_dias)]

        # ── Últimos 30 días: RevPAR, ADR, ocupación real ────────────────
        historico_30 = dict(await conn.fetchrow("""
            SELECT
                ROUND(SUM(r.tarifa_noche * r.noches)
                      / NULLIF(SUM(r.noches), 0), 0)                      AS adr_30d,
                ROUND(
                    SUM(r.noches * r.tarifa_noche)
                    / NULLIF($1 * 30.0, 0)
                , 0)                                                       AS revpar_30d,
                ROUND(
                    SUM(r.noches) * 100.0 / NULLIF($1 * 30.0, 0)
                , 1)                                                       AS ocupacion_30d
            FROM reservas r
            WHERE r.fecha_salida BETWEEN CURRENT_DATE - 30 AND CURRENT_DATE
              AND r.estado = 'checkout'
        """, hab_activas))

        # ── Últimos 7 días ───────────────────────────────────────────────
        historico_7 = dict(await conn.fetchrow("""
            SELECT
                ROUND(SUM(r.tarifa_noche * r.noches)
                      / NULLIF(SUM(r.noches), 0), 0)                     AS adr_7d,
                ROUND(
                    SUM(r.noches * r.tarifa_noche) / NULLIF($1 * 7.0, 0)
                , 0)                                                      AS revpar_7d,
                ROUND(
                    SUM(r.noches) * 100.0 / NULLIF($1 * 7.0, 0)
                , 1)                                                      AS ocupacion_7d
            FROM reservas r
            WHERE r.fecha_salida BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE
              AND r.estado = 'checkout'
        """, hab_activas))

        # ── Performance por canal (últimos 30 días) ──────────────────────
        canales = [dict(r) for r in await conn.fetch("""
            SELECT
                cv.nombre                                                     AS canal,
                COUNT(r.id)                                                   AS reservas,
                ROUND(SUM(r.total_hospedaje), 0)                             AS ingresos_brutos,
                ROUND(AVG(r.tarifa_noche), 0)                                AS adr,
                cv.comision_pct,
                ROUND(SUM(r.total_hospedaje) * (1 - cv.comision_pct / 100), 0) AS ingresos_netos
            FROM reservas r
            JOIN canales_venta cv ON cv.id = r.canal_id
            WHERE r.fecha_salida BETWEEN CURRENT_DATE - 30 AND CURRENT_DATE
              AND r.estado = 'checkout'
            GROUP BY cv.nombre, cv.comision_pct
            ORDER BY ingresos_netos DESC
        """)]

    # ── Cálculos derivados ─────────────────────────────────────────────
    def _f(v):
        return float(v) if isinstance(v, Decimal) else float(v or 0)

    ocupadas_hoy  = int(snapshot["ocupadas"] or 0)
    adr_hoy       = _f(snapshot["adr"])
    ocupacion_hoy = round(ocupadas_hoy * 100 / hab_activas, 1) if hab_activas else 0
    revpar_hoy    = round(adr_hoy * ocupacion_hoy / 100, 0)

    # Semana próxima: resumen
    proxima_semana = calendar_rows[:7]
    ocu_max_7d = max((r["reservas"] for r in proxima_semana), default=0)
    ocu_avg_7d = round(
        sum(r["reservas"] for r in proxima_semana) * 100 / (hab_activas * 7), 1
    ) if hab_activas else 0

    # Oportunidades de precio: días futuros con ocupación alta y ADR bajo
    oportunidades = []
    for r in calendar_rows:
        ocu_pct = _f(r["ocupacion_pct"])
        adr_dia  = _f(r["adr"]) if r["adr"] else None
        if ocu_pct < OCUPACION_ALTA_PCT or adr_dia is None:
            continue
        if adr_ref > 0 and adr_dia < adr_ref * (1 - DESCUENTO_UMBRAL_PCT / 100):
            oportunidades.append({
                "fecha":       str(r["fecha"]),
                "ocupacion_pct": ocu_pct,
                "adr_actual":  adr_dia,
                "adr_referencia": adr_ref,
                "diferencia_pct": round((adr_ref - adr_dia) * 100 / adr_ref, 1),
            })

    return {
        "fecha": str(hoy),
        "hab_activas": hab_activas,
        "snapshot": {
            "ocupadas":      ocupadas_hoy,
            "ocupacion_pct": ocupacion_hoy,
            "adr":           adr_hoy,
            "revpar":        revpar_hoy,
            "checkins_hoy":  int(snapshot["checkins_hoy"] or 0),
        },
        "historico": {
            "7d": {
                "adr":          _f(historico_7["adr_7d"]),
                "revpar":       _f(historico_7["revpar_7d"]),
                "ocupacion_pct":_f(historico_7["ocupacion_7d"]),
            },
            "30d": {
                "adr":          _f(historico_30["adr_30d"]),
                "revpar":       _f(historico_30["revpar_30d"]),
                "ocupacion_pct":_f(historico_30["ocupacion_30d"]),
            },
        },
        "adr_referencia": adr_ref,
        "tarifa_rack":    tarifa_rack,
        "proyeccion": {
            "horizon_dias":  horizon_dias,
            "calendario":    [
                {
                    "fecha":        str(r["fecha"]),
                    "reservas":     int(r["reservas"] or 0),
                    "ocupacion_pct":_f(r["ocupacion_pct"]),
                    "adr":          _f(r["adr"]) if r["adr"] else None,
                }
                for r in calendar_rows
            ],
            "ocupacion_prom_7d": ocu_avg_7d,
            "pico_reservas_7d":  ocu_max_7d,
        },
        "canales":       [
            {
                "canal":           r["canal"],
                "reservas":        int(r["reservas"] or 0),
                "ingresos_brutos": _f(r["ingresos_brutos"]),
                "ingresos_netos":  _f(r["ingresos_netos"]),
                "adr":             _f(r["adr"]),
                "comision_pct":    _f(r["comision_pct"]),
            }
            for r in canales
        ],
        "oportunidades_precio": oportunidades,
    }


# ─────────────────────────────────────────────────────────────
# Renderizado
# ─────────────────────────────────────────────────────────────

def _fmt(v: float, cfg: dict) -> str:
    cur = cfg.get("currency", {})
    sym = cur.get("symbol", "$")
    sep = cur.get("thousands_separator", ".")
    return f"{sym}{v:,.0f}".replace(",", sep)


def renderizar_revenue_markdown(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: _fmt(v, cfg)
    s   = data["snapshot"]
    h7  = data["historico"]["7d"]
    h30 = data["historico"]["30d"]

    lines = [
        f"## 📊 Revenue Management — {biz}",
        f"**Fecha:** {data['fecha']} · {data['hab_activas']} habitaciones activas",
        "",
        "### Hoy",
        "| Ocupación | Ocupadas | ADR | RevPAR |",
        "|---|---|---|---|",
        f"| **{s['ocupacion_pct']:.1f}%** | {s['ocupadas']}/{data['hab_activas']} "
        f"| {fm(s['adr'])} | {fm(s['revpar'])} |",
        "",
        "### Tendencia",
        "| Período | Ocupación | ADR | RevPAR |",
        "|---|---|---|---|",
        f"| Últimos 7d | {h7['ocupacion_pct']:.1f}% | {fm(h7['adr'])} | {fm(h7['revpar'])} |",
        f"| Últimos 30d | {h30['ocupacion_pct']:.1f}% | {fm(h30['adr'])} | {fm(h30['revpar'])} |",
    ]

    # Próximos 7 días
    cal7 = data["proyeccion"]["calendario"][:7]
    if any(r["reservas"] > 0 for r in cal7):
        lines += ["", "### Próximos 7 días", "| Fecha | Reservas | Ocupación | ADR |",
                  "|---|---|---|---|"]
        for r in cal7:
            adr_txt = fm(r["adr"]) if r["adr"] else "—"
            lines.append(
                f"| {r['fecha']} | {r['reservas']} | {r['ocupacion_pct']:.1f}% | {adr_txt} |"
            )

    if data["canales"]:
        lines += ["", "### Canales (últimos 30d)",
                  "| Canal | Reservas | Ingresos brutos | Comisión | Neto |",
                  "|---|---|---|---|---|"]
        for c in data["canales"]:
            com = f"{c['comision_pct']:.1f}%"
            lines.append(
                f"| {c['canal']} | {c['reservas']} | {fm(c['ingresos_brutos'])} "
                f"| {com} | {fm(c['ingresos_netos'])} |"
            )

    if data["oportunidades_precio"]:
        lines += ["", "### 💡 Oportunidades de precio"]
        for o in data["oportunidades_precio"]:
            lines.append(
                f"- **{o['fecha']}** — {o['ocupacion_pct']:.1f}% ocupado, "
                f"ADR actual {fm(o['adr_actual'])} vs referencia {fm(o['adr_referencia'])} "
                f"(-{o['diferencia_pct']:.1f}%)"
            )

    return "\n".join(lines)


def build_discord_embed_revenue(data: dict, cfg: dict) -> dict:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: _fmt(v, cfg)
    s   = data["snapshot"]
    h7  = data["historico"]["7d"]
    h30 = data["historico"]["30d"]
    oport = data["oportunidades_precio"]

    # Color según ocupación
    ocu = s["ocupacion_pct"]
    color = 0x2ECC71 if ocu >= 70 else (0xF39C12 if ocu >= 40 else 0xE74C3C)

    # Próximos 7 días como mini-tabla
    cal7 = data["proyeccion"]["calendario"][:7]
    cal_txt = "\n".join(
        f"`{r['fecha'][5:]}` {r['ocupacion_pct']:.0f}% "
        + (f"· {fm(r['adr'])}" if r["adr"] else "· —")
        for r in cal7
    ) or "Sin reservas"

    # Canales top 3
    canales_txt = "\n".join(
        f"{c['canal']}: {fm(c['ingresos_netos'])} neto ({c['comision_pct']:.0f}% com.)"
        for c in data["canales"][:3]
    ) or "—"

    fields = [
        {
            "name":   "📍 Hoy",
            "value":  (
                f"Ocupación: **{s['ocupacion_pct']:.1f}%** ({s['ocupadas']}/{data['hab_activas']})\n"
                f"ADR: **{fm(s['adr'])}**\n"
                f"RevPAR: **{fm(s['revpar'])}**"
            ),
            "inline": True,
        },
        {
            "name":   "📈 Tendencia",
            "value":  (
                f"7d: ocu {h7['ocupacion_pct']:.1f}% · ADR {fm(h7['adr'])}\n"
                f"30d: ocu {h30['ocupacion_pct']:.1f}% · ADR {fm(h30['adr'])}\n"
                f"RevPAR 30d: {fm(h30['revpar'])}"
            ),
            "inline": True,
        },
        {
            "name":   "📅 Próximos 7 días",
            "value":  cal_txt,
            "inline": False,
        },
        {
            "name":   "🏪 Canales (30d)",
            "value":  canales_txt,
            "inline": True,
        },
    ]

    if oport:
        oport_txt = "\n".join(
            f"💡 {o['fecha'][5:]}: {o['ocupacion_pct']:.0f}% ocup. · "
            f"ADR {fm(o['adr_actual'])} (-{o['diferencia_pct']:.1f}% vs ref.)"
            for o in oport[:3]
        )
        fields.append({
            "name":   "💡 Oportunidades de precio",
            "value":  oport_txt,
            "inline": False,
        })

    return {
        "embeds": [{
            "title":  f"📊 Revenue Management — {biz} · {data['fecha']}",
            "color":  color,
            "fields": fields,
        }]
    }
