"""
Agente de Cash Flow.

Proyecta ingresos esperados (reservas confirmadas futuras) vs gastos estimados
(promedio histórico semanal) para las próximas 8 semanas.
Incluye cobros pendientes y semáforo de liquidez.
Sin LLM — SQL puro.
"""

import logging
from datetime import date, timedelta

from .. import config
from ._common import SEMAFORO_COLOR, SEMAFORO_ICONO, fmt_moneda, to_float

logger = logging.getLogger(__name__)

SEMANAS          = 8     # horizonte de proyección
SEMANAS_HISTORIA = 12    # semanas de historial para calcular promedio de gastos
# Umbral de alerta: semanas de gastos disponibles en el acumulado mínimo
UMBRAL_ALERTA_SEMANAS   = 2
UMBRAL_CRITICO_SEMANAS  = 0


async def calcular_cash_flow() -> dict:
    hoy      = date.today()
    lunes    = hoy - timedelta(days=hoy.weekday())   # lunes de esta semana
    hist_ini = lunes - timedelta(weeks=SEMANAS_HISTORIA)

    async with config.db_pool.acquire() as conn:

        # ── Ingresos proyectados por semana (checkout de reservas confirmadas) ──
        ing_rows = [dict(r) for r in await conn.fetch("""
            SELECT
                DATE_TRUNC('week', fecha_salida)::date    AS semana,
                COUNT(*)                                  AS reservas,
                COALESCE(SUM(total_hospedaje), 0)         AS ingresos
            FROM reservas
            WHERE estado     = 'confirmada'
              AND fecha_salida > CURRENT_DATE
              AND fecha_salida <= CURRENT_DATE + ($1 * 7)
            GROUP BY DATE_TRUNC('week', fecha_salida)
            ORDER BY semana
        """, SEMANAS)]

        # ── Promedio de gastos semanal histórico ─────────────────────────
        gasto_stats = dict(await conn.fetchrow("""
            SELECT
                ROUND(AVG(total_semana), 0)  AS promedio_semanal,
                ROUND(MAX(total_semana), 0)  AS maximo_semanal,
                ROUND(MIN(total_semana), 0)  AS minimo_semanal,
                COUNT(*)                     AS semanas_con_datos
            FROM (
                SELECT DATE_TRUNC('week', fecha)::date AS semana,
                       SUM(monto)                       AS total_semana
                FROM gastos
                WHERE fecha BETWEEN $1 AND CURRENT_DATE
                GROUP BY DATE_TRUNC('week', fecha)
            ) t
        """, hist_ini))

        # ── Gastos por categoría (promedio semanal histórico) ───────────
        gasto_cat = [dict(r) for r in await conn.fetch("""
            SELECT
                categoria,
                ROUND(AVG(semana_monto), 0) AS promedio_semanal
            FROM (
                SELECT
                    DATE_TRUNC('week', g.fecha)::date          AS semana,
                    COALESCE(cg.nombre, 'Sin categoría')        AS categoria,
                    SUM(g.monto)                               AS semana_monto
                FROM gastos g
                LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
                WHERE g.fecha BETWEEN $1 AND CURRENT_DATE
                GROUP BY DATE_TRUNC('week', g.fecha),
                         COALESCE(cg.nombre, 'Sin categoría')
            ) t
            GROUP BY categoria
            ORDER BY promedio_semanal DESC
        """, hist_ini)]

        # ── Cobros pendientes ────────────────────────────────────────────
        pendientes = dict(await conn.fetchrow("""
            SELECT
                COALESCE(SUM(p.monto), 0)   AS total_pendiente,
                COUNT(*)                    AS n_pagos,
                COALESCE(SUM(p.monto) FILTER (
                    WHERE r.fecha_salida <= CURRENT_DATE + 14
                ), 0)                       AS vence_14d
            FROM pagos p
            JOIN reservas r ON r.id = p.reserva_id
            WHERE p.estado = 'pendiente'
        """))

        # ── Cobros reales últimos 30 días (referencia de caja activa) ───
        cobrado_30d = float(await conn.fetchval("""
            SELECT COALESCE(SUM(monto), 0)
            FROM pagos
            WHERE estado = 'pagado' AND fecha >= CURRENT_DATE - 30
        """) or 0)

        # ── Gastos reales últimas 4 semanas ─────────────────────────────
        gastado_4s = float(await conn.fetchval("""
            SELECT COALESCE(SUM(monto), 0)
            FROM gastos
            WHERE fecha >= CURRENT_DATE - 28
        """) or 0)

    # ── Construir tabla semanal ────────────────────────────────────────
    _f = to_float

    promedio_gastos = _f(gasto_stats["promedio_semanal"])

    # Índice de ingresos proyectados por semana
    ing_index = {str(r["semana"]): _f(r["ingresos"]) for r in ing_rows}
    res_index = {str(r["semana"]): int(r["reservas"] or 0) for r in ing_rows}

    semanas_proyeccion = []
    acumulado = 0.0
    for i in range(SEMANAS):
        semana_ini = lunes + timedelta(weeks=i)
        semana_fin = semana_ini + timedelta(days=6)
        clave      = str(semana_ini)

        ing  = ing_index.get(clave, 0.0)
        gas  = promedio_gastos
        neto = ing - gas
        acumulado += neto

        semanas_proyeccion.append({
            "semana_inicio": clave,
            "semana_fin":    str(semana_fin),
            "reservas":      res_index.get(clave, 0),
            "ingresos":      ing,
            "gastos_est":    gas,
            "flujo_neto":    neto,
            "acumulado":     round(acumulado, 2),
        })

    # ── Semáforo de liquidez ──────────────────────────────────────────
    min_acumulado = min(s["acumulado"] for s in semanas_proyeccion)
    if promedio_gastos > 0:
        semanas_cobertura = round(min_acumulado / promedio_gastos, 1)
    else:
        semanas_cobertura = None

    if min_acumulado < 0:
        semaforo = "critico"
    elif semanas_cobertura is not None and semanas_cobertura < UMBRAL_ALERTA_SEMANAS:
        semaforo = "alerta"
    else:
        semaforo = "ok"

    total_ing_proy = sum(s["ingresos"] for s in semanas_proyeccion)
    total_gas_proy = promedio_gastos * SEMANAS

    return {
        "fecha":          str(hoy),
        "horizon_semanas": SEMANAS,
        "semaforo":       semaforo,
        "resumen": {
            "ingresos_proyectados":  total_ing_proy,
            "gastos_estimados":      total_gas_proy,
            "flujo_neto_proyectado": total_ing_proy - total_gas_proy,
            "cobros_pendientes":     _f(pendientes["total_pendiente"]),
            "pendiente_vence_14d":   _f(pendientes["vence_14d"]),
            "cobrado_30d":           cobrado_30d,
            "gastado_4s":            gastado_4s,
            "promedio_gastos_semanal": promedio_gastos,
            "min_acumulado":         min_acumulado,
            "semanas_cobertura":     semanas_cobertura,
        },
        "semanas":        semanas_proyeccion,
        "gastos_por_categoria": [
            {"categoria": r["categoria"], "promedio_semanal": _f(r["promedio_semanal"])}
            for r in gasto_cat
        ],
    }


# ─────────────────────────────────────────────────────────────
# Renderizado
# ─────────────────────────────────────────────────────────────

def renderizar_cash_flow_markdown(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)
    r   = data["resumen"]
    sem = data["semaforo"]
    ico = SEMAFORO_ICONO[sem]

    cobertura_txt = (
        f"{r['semanas_cobertura']:.1f} semanas de gastos"
        if r["semanas_cobertura"] is not None else "—"
    )

    lines = [
        f"## 💵 Cash Flow — {biz}",
        f"**Fecha:** {data['fecha']} · Horizonte: {data['horizon_semanas']} semanas",
        f"**Liquidez:** {ico} {sem.upper()} — cobertura mínima {cobertura_txt}",
        "",
        "### Resumen",
        "| | Monto |",
        "|---|---|",
        f"| Cobrado últimos 30d | {fm(r['cobrado_30d'])} |",
        f"| Gastado últimas 4s  | {fm(r['gastado_4s'])} |",
        f"| Cobros pendientes   | {fm(r['cobros_pendientes'])} |",
        f"| Vence en 14 días    | {fm(r['pendiente_vence_14d'])} |",
        f"| Gastos est. / semana| {fm(r['promedio_gastos_semanal'])} |",
        "",
        "### Proyección semanal",
        "| Semana | Ingresos | Gastos est. | Flujo neto | Acumulado |",
        "|---|---|---|---|---|",
    ]
    for s in data["semanas"]:
        neto_txt = fm(s["flujo_neto"])
        acu_txt  = fm(s["acumulado"])
        signo    = "▼" if s["flujo_neto"] < 0 else "▲" if s["flujo_neto"] > 0 else "—"
        lines.append(
            f"| {s['semana_inicio']} | {fm(s['ingresos'])} | "
            f"{fm(s['gastos_est'])} | {signo} {neto_txt} | {acu_txt} |"
        )

    if data["gastos_por_categoria"]:
        lines += ["", "### Estructura de gastos (promedio semanal)",
                  "| Categoría | Promedio / semana |",
                  "|---|---|"]
        for g in data["gastos_por_categoria"]:
            lines.append(f"| {g['categoria']} | {fm(g['promedio_semanal'])} |")

    return "\n".join(lines)


def build_discord_embed_cash_flow(data: dict, cfg: dict) -> dict:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)
    r   = data["resumen"]
    sem = data["semaforo"]
    ico = SEMAFORO_ICONO[sem]

    cobertura_txt = (
        f"{r['semanas_cobertura']:.1f} sem."
        if r["semanas_cobertura"] is not None else "—"
    )

    # Proyección: próximas 4 semanas en texto compacto
    proy_lines = []
    for s in data["semanas"][:4]:
        signo = "▼" if s["flujo_neto"] < 0 else "▲"
        proy_lines.append(
            f"`{s['semana_inicio'][5:]}` {signo} {fm(s['flujo_neto'])} "
            f"→ acum. {fm(s['acumulado'])}"
        )
    proy_txt = "\n".join(proy_lines) or "Sin reservas confirmadas"

    # Gastos top 3
    gas_txt = "\n".join(
        f"{g['categoria']}: {fm(g['promedio_semanal'])}/sem"
        for g in data["gastos_por_categoria"][:3]
    ) or "—"

    fields = [
        {
            "name":   f"{ico} Liquidez",
            "value":  (
                f"Estado: **{sem.upper()}**\n"
                f"Cobertura mínima: **{cobertura_txt}**\n"
                f"Acumulado mín.: {fm(r['min_acumulado'])}"
            ),
            "inline": True,
        },
        {
            "name":   "💰 Situación actual",
            "value":  (
                f"Cobrado 30d: {fm(r['cobrado_30d'])}\n"
                f"Gastado 4s: {fm(r['gastado_4s'])}\n"
                f"Pendiente cobro: **{fm(r['cobros_pendientes'])}**\n"
                f"Vence 14d: {fm(r['pendiente_vence_14d'])}"
            ),
            "inline": True,
        },
        {
            "name":   "📅 Próximas 4 semanas",
            "value":  proy_txt,
            "inline": False,
        },
        {
            "name":   "📋 Gastos estimados/semana",
            "value":  f"**Total: {fm(r['promedio_gastos_semanal'])}**\n" + gas_txt,
            "inline": True,
        },
        {
            "name":   "📊 Proyección 8 semanas",
            "value":  (
                f"Ingresos: {fm(r['ingresos_proyectados'])}\n"
                f"Gastos est.: {fm(r['gastos_estimados'])}\n"
                f"Flujo neto: **{fm(r['flujo_neto_proyectado'])}**"
            ),
            "inline": True,
        },
    ]

    return {
        "embeds": [{
            "title":  f"💵 Cash Flow — {biz} · {data['fecha']}",
            "color":  SEMAFORO_COLOR[sem],
            "fields": fields,
        }]
    }
