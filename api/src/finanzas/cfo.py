"""
Agente CFO Virtual (horizontal).

No calcula nada nuevo: consolida la salida de los demás agentes financieros
(P&L, Tesorería, Cuentas por Cobrar/Pagar, Presupuesto y Copiloto Tributario) en
un informe ejecutivo con semáforos y puntos clave. Es determinístico (sin LLM):
así los montos del cliente nunca salen a un modelo externo. Cada bloque se obtiene
de forma defensiva; si un agente falla, el resto del informe se entrega igual.
"""

import logging
from datetime import date

from src.verticals import dispatch
from src.finanzas.tesoreria import calcular_tesoreria
from src.finanzas.cuentas_por_cobrar import calcular_cuentas_por_cobrar
from src.finanzas.cuentas_por_pagar import calcular_cuentas_por_pagar
from src.finanzas.presupuesto import calcular_presupuesto

logger = logging.getLogger(__name__)


async def _safe(coro, etiqueta: str):
    try:
        return await coro
    except Exception as e:                       # noqa: BLE001 — un agente caído no debe tumbar el CFO
        logger.warning(f"[cfo] {etiqueta} no disponible: {e}")
        return None


async def calcular_cfo(hasta: date) -> dict:
    pnl   = await _safe(dispatch.pnl().calcular_pnl(hasta), "pnl")
    teso  = await _safe(calcular_tesoreria(hasta), "tesoreria")
    cxc   = await _safe(calcular_cuentas_por_cobrar(hasta), "cxc")
    cxp   = await _safe(calcular_cuentas_por_pagar(hasta), "cxp")
    presu = await _safe(calcular_presupuesto(hasta), "presupuesto")
    trib  = await _safe(dispatch.tributario().calcular_tributario_semanal(hasta), "tributario")

    puntos: list[dict] = []

    def alerta(nivel, texto):
        puntos.append({"nivel": nivel, "texto": texto})

    # Rentabilidad
    if pnl:
        r = pnl.get("resumen", {})
        if r.get("resultado_neto", 0) < 0:
            alerta("critico", "Resultado neto negativo en el período.")
        var = r.get("var_resultado_pct")
        if var is not None and var < -10:
            alerta("alerta", f"El resultado cae {var:.0f}% vs el año anterior.")

    # Liquidez
    if teso:
        if teso.get("semaforo") == "critico":
            alerta("critico", "Liquidez crítica: la caja proyectada se vuelve negativa.")
        elif teso.get("semaforo") == "alerta":
            alerta("alerta", "Liquidez ajustada en las próximas semanas.")
        postergar = [p for p in teso.get("propuesta_pagos", []) if p["accion"] == "postergar"]
        if postergar:
            alerta("alerta", f"{len(postergar)} pago(s) no caben en la caja proyectada a 30 días.")

    # Cobranza
    if cxc and cxc.get("dso") is not None and cxc["dso"] > 45:
        alerta("alerta", f"DSO alto: {cxc['dso']:.0f} días de cobro pendiente.")
    if cxc and cxc.get("vencido_60_mas", 0) > 0:
        alerta("alerta", "Cartera con saldos de más de 60 días.")

    # Pagos
    if cxp and cxp.get("vencido", 0) > 0:
        alerta("alerta", "Hay facturas de proveedores vencidas.")

    # Presupuesto
    if presu and presu.get("tiene_presupuesto"):
        for d in presu.get("desviaciones", []):
            if not d.get("favorable"):
                alerta("info", f"Desviación presupuestaria en {d['categoria']} "
                               f"({d['var_pct']:+.0f}%).")

    # Tributario
    if trib:
        score = (trib.get("agente_riesgo") or {}).get("score_riesgo")
        if score == "alto":
            alerta("critico", "Riesgo tributario alto detectado.")
        elif score == "medio":
            alerta("alerta", "Riesgo tributario medio.")

    niveles = {p["nivel"] for p in puntos}
    semaforo = "critico" if "critico" in niveles else "alerta" if "alerta" in niveles else "ok"

    return {
        "corte": str(hasta),
        "semaforo": semaforo,
        "puntos_clave": puntos,
        "indicadores": {
            "rentabilidad": (pnl or {}).get("resumen"),
            "liquidez": {"semaforo": (teso or {}).get("semaforo"),
                         "caja_estimada": (teso or {}).get("caja_estimada"),
                         "caja_proyectada_8sem": (teso or {}).get("caja_proyectada_8sem")},
            "por_cobrar": {"total": (cxc or {}).get("total_por_cobrar"),
                           "dso": (cxc or {}).get("dso")},
            "por_pagar": {"total": (cxp or {}).get("total_por_pagar"),
                          "vencido": (cxp or {}).get("vencido")},
            "presupuesto": {"tiene": (presu or {}).get("tiene_presupuesto", False)},
            "tributario": {"riesgo": (trib or {}).get("agente_riesgo", {}).get("score_riesgo")
                           if trib else None},
        },
    }


def renderizar_cfo_markdown(data: dict) -> str:
    semf = {"ok": "🟢", "alerta": "🟡", "critico": "🔴"}.get(data["semaforo"], "")
    ind = data["indicadores"]
    out = ["# CFO Virtual — Resumen Ejecutivo",
           f"\nCorte: {data['corte']} · estado general {semf} {data['semaforo']}"]

    rent = ind.get("rentabilidad") or {}
    if rent:
        out.append(f"- Rentabilidad: margen {rent.get('margen_bruto_pct', 0):.0f}% · "
                   f"resultado neto ${rent.get('resultado_neto', 0):,.0f}")
    liq = ind["liquidez"]
    if liq.get("caja_estimada") is not None:
        out.append(f"- Liquidez ({liq.get('semaforo')}): caja ${liq['caja_estimada']:,.0f} → "
                   f"${liq.get('caja_proyectada_8sem', 0):,.0f} a 8 semanas")
    pc = ind["por_cobrar"]
    if pc.get("total") is not None:
        dso = pc.get("dso")
        out.append(f"- Por cobrar: ${pc['total']:,.0f}" + (f" · DSO {dso:.0f}d" if dso else ""))
    pp = ind["por_pagar"]
    if pp.get("total") is not None:
        out.append(f"- Por pagar: ${pp['total']:,.0f} (vencido ${pp.get('vencido', 0):,.0f})")
    if ind["tributario"].get("riesgo"):
        out.append(f"- Riesgo tributario: {ind['tributario']['riesgo']}")

    out.append("\n## Puntos clave")
    if data["puntos_clave"]:
        ic = {"critico": "🔴", "alerta": "🟡", "info": "🔵"}
        for p in data["puntos_clave"]:
            out.append(f"- {ic.get(p['nivel'], '•')} {p['texto']}")
    else:
        out.append("- Sin alertas: indicadores dentro de lo esperado.")
    return "\n".join(out)
