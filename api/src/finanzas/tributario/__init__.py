"""
Motor del Copiloto Tributario (horizontal).

`calcular_tributario_semanal(hasta, ingresos_fn)` orquesta IVA/F29, Cumplimiento
y Riesgo para cualquier vertical. El vertical solo aporta `ingresos_fn` (qué
cuenta como ingreso afecto). Reutilizable por hotel, restaurante, etc.
"""

import logging
from datetime import date, timedelta

from src import config
from src.finanzas.economia import obtener_uf
from .iva import calcular_iva
from .riesgo import calcular_riesgo
from .cumplimiento import calcular_cumplimiento

logger = logging.getLogger(__name__)

__all__ = ["calcular_tributario_semanal", "renderizar_tributario_markdown"]


async def calcular_tributario_semanal(hasta: date, ingresos_fn) -> dict:
    """Orquesta los agentes tributarios. `ingresos_fn(conn, ini, fin)` lo da el vertical."""
    desde      = hasta - timedelta(days=6)
    inicio_mes = date(hasta.year, hasta.month, 1)

    uf = await obtener_uf()
    if uf:
        logger.info(f"UF del día: ${uf:,.2f}")

    async with config.db_pool.acquire() as conn:
        iva    = await calcular_iva(conn, hasta, ingresos_fn, uf)
        riesgo = await calcular_riesgo(conn, hasta, iva, ingresos_fn, uf)

    cumplimiento = calcular_cumplimiento(hasta)

    return {
        "periodo": {
            "semana": {"inicio": str(desde), "fin": str(hasta)},
            "mes":    {"inicio": str(inicio_mes), "fin": str(hasta)},
        },
        "agente_iva":          iva,
        "agente_cumplimiento": cumplimiento,
        "agente_riesgo":       riesgo,
    }


def renderizar_tributario_markdown(data: dict) -> str:
    iva = data.get("agente_iva", {})
    cum = data.get("agente_cumplimiento", {})
    rie = data.get("agente_riesgo", {})
    acum = iva.get("acumulado_mes", {})
    f29  = iva.get("f29", {})

    out = ["# Copiloto Tributario\n"]
    out.append("## Agente IVA")
    out.append(f"- IVA débito (mes): ${acum.get('iva_debito_acum', 0):,.0f}")
    out.append(f"- IVA crédito (mes): ${acum.get('iva_credito_acum', 0):,.0f}")
    out.append(f"- Saldo IVA: ${acum.get('saldo_iva', 0):,.0f} "
               f"({acum.get('saldo_iva_uf', 0):.1f} UF) — {acum.get('estado', '')}")
    out.append(f"- F29 período {f29.get('periodo', '')}: a pagar ${f29.get('total_a_pagar', 0):,.0f} "
               f"· vence {f29.get('vencimiento', '')} (en {f29.get('dias_para_vencimiento', 0)} días)\n")

    out.append("## Agente Cumplimiento — próximos vencimientos")
    venc = cum.get("proximos_vencimientos", [])
    if venc:
        for v in venc:
            out.append(f"- {v['fecha']} · {v['nombre']} (en {v['dias_restantes']} días)")
    else:
        out.append("- Sin vencimientos en el horizonte.")
    out.append("")

    out.append(f"## Agente Riesgo — nivel: {rie.get('score_riesgo', 'n/a')}")
    for i in rie.get("inconsistencias", []):
        out.append(f"- [{i['nivel']}] {i['titulo']}: {i['descripcion']}")
    for a in rie.get("alertas", []):
        out.append(f"- ALERTA [{a['nivel']}] {a['titulo']}: {a['descripcion']}")
    if not rie.get("inconsistencias") and not rie.get("alertas"):
        out.append("- Sin inconsistencias ni alertas detectadas.")

    return "\n".join(out)
