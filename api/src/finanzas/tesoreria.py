"""
Agente Tesorería (horizontal) — versión rica que reemplaza al cash_flow simple.

Consolida la posición de caja y proyecta la liquidez a 8 semanas combinando:
  - flujo recurrente: promedio semanal de cobros (pagos) y egresos (gastos) de 90 días;
  - cobros esperados: cartera de Cuentas por Cobrar;
  - compromisos: vencimientos de Cuentas por Pagar.
Genera además una propuesta de pagos: ordena las CxP por urgencia y marca cuáles
caben en la caja proyectada a 30 días. Sin LLM — SQL puro.
"""

import logging
from datetime import date, timedelta

from src import config
from src.agents._common import to_float, fetchval_opt
from src.finanzas.cuentas_por_pagar import calcular_cuentas_por_pagar
from src.finanzas.cuentas_por_cobrar import calcular_cuentas_por_cobrar

logger = logging.getLogger(__name__)

_SEMANAS = 8


async def _posicion_caja(conn, hasta: date) -> tuple[float, str]:
    """Caja estimada: saldo de la cartola si hay movimientos; si no, flujo neto 30d."""
    saldo = await conn.fetchval(
        "SELECT COALESCE(SUM(monto), 0) FROM movimientos_bancarios WHERE fecha <= $1", hasta)
    if saldo is not None and await conn.fetchval(
            "SELECT COUNT(*) FROM movimientos_bancarios WHERE fecha <= $1", hasta):
        return round(to_float(saldo), 2), "cartola"
    desde_30 = hasta - timedelta(days=29)
    ing = to_float(await fetchval_opt(conn,
        "SELECT COALESCE(SUM(monto),0) FROM pagos WHERE fecha BETWEEN $1 AND $2", desde_30, hasta) or 0)
    egr = to_float(await conn.fetchval(
        "SELECT COALESCE(SUM(monto),0) FROM gastos WHERE fecha BETWEEN $1 AND $2", desde_30, hasta) or 0)
    return round(ing - egr, 2), "flujo_30d"


async def calcular_tesoreria(hasta: date) -> dict:
    desde_90 = hasta - timedelta(days=89)
    async with config.db_pool.acquire() as conn:
        caja, fuente_caja = await _posicion_caja(conn, hasta)
        cobros_90 = to_float(await fetchval_opt(conn,
            "SELECT COALESCE(SUM(monto),0) FROM pagos WHERE fecha BETWEEN $1 AND $2",
            desde_90, hasta) or 0)
        egresos_90 = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto),0) FROM gastos WHERE fecha BETWEEN $1 AND $2",
            desde_90, hasta) or 0)

    cxp = await calcular_cuentas_por_pagar(hasta)
    cxc = await calcular_cuentas_por_cobrar(hasta)

    cobro_sem  = round(cobros_90 / 13, 2)     # ~13 semanas en 90 días
    egreso_sem = round(egresos_90 / 13, 2)
    neto_sem   = round(cobro_sem - egreso_sem, 2)

    # Forecast 8 semanas (flujo recurrente sobre la caja estimada)
    proyeccion, acumulado = [], caja
    for s in range(1, _SEMANAS + 1):
        acumulado = round(acumulado + neto_sem, 2)
        proyeccion.append({"semana": s, "entrada": cobro_sem, "salida": egreso_sem,
                           "neto": neto_sem, "caja_proyectada": acumulado})

    # Propuesta de pagos: CxP por urgencia vs caja proyectada a 30 días
    caja_30d = round(caja + cobro_sem * 4, 2)
    compromisos = (cxp.get("vencidas", []) + cxp.get("proximos_vencimientos", []))
    propuesta, disponible = [], caja_30d
    for c in compromisos:
        cabe = disponible >= c["monto"]
        if cabe:
            disponible = round(disponible - c["monto"], 2)
        propuesta.append({**c, "accion": "pagar" if cabe else "postergar"})

    if neto_sem >= 0 and caja >= 0:
        semaforo = "ok"
    elif acumulado >= 0:
        semaforo = "alerta"
    else:
        semaforo = "critico"

    return {
        "corte": str(hasta),
        "semaforo": semaforo,
        "caja_estimada": caja,
        "fuente_caja": fuente_caja,
        "flujo_semanal": {"cobros": cobro_sem, "egresos": egreso_sem, "neto": neto_sem},
        "caja_proyectada_8sem": acumulado,
        "proyeccion": proyeccion,
        "cobros_esperados": cxc.get("total_por_cobrar", 0.0),
        "compromisos": {"total": cxp.get("total_por_pagar", 0.0),
                        "vencido": cxp.get("vencido", 0.0)},
        "propuesta_pagos": propuesta[:10],
    }


def renderizar_tesoreria_markdown(data: dict) -> str:
    f = data["flujo_semanal"]
    semf = {"ok": "🟢", "alerta": "🟡", "critico": "🔴"}.get(data["semaforo"], "")
    out = ["# Tesorería",
           f"\nCorte: {data['corte']} · liquidez {semf} {data['semaforo']}",
           f"- Caja estimada: ${data['caja_estimada']:,.0f} ({data['fuente_caja']})",
           f"- Flujo semanal: cobros ${f['cobros']:,.0f} − egresos ${f['egresos']:,.0f} "
           f"= neto ${f['neto']:,.0f}",
           f"- Caja proyectada a 8 semanas: ${data['caja_proyectada_8sem']:,.0f}",
           f"- Por cobrar: ${data['cobros_esperados']:,.0f} · "
           f"Por pagar: ${data['compromisos']['total']:,.0f} "
           f"(vencido ${data['compromisos']['vencido']:,.0f})"]
    if data["propuesta_pagos"]:
        out.append("\n## Propuesta de pagos (por urgencia)")
        for p in data["propuesta_pagos"]:
            ic = "✅" if p["accion"] == "pagar" else "⏸️"
            out.append(f"- {ic} {p['vence']} · {p['proveedor']} · ${p['monto']:,.0f} "
                       f"→ {p['accion']}")
    return "\n".join(out)
