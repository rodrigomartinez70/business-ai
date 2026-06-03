"""
Copiloto Tributario — restaurante. Orquesta IVA/F29 (sobre pedidos),
Cumplimiento (calendario, reutilizado) y Riesgo. Reutiliza el renderer markdown
y la UF del Banco Central (agnósticos al vertical).
"""

import logging
from datetime import date, timedelta

from src import config
from src.verticals.hotel.economia import obtener_uf
from src.verticals.hotel.agents.tributario import renderizar_tributario_markdown
from src.verticals.hotel.agents.tributario.cumplimiento import calcular_cumplimiento
from .iva import calcular_iva
from .riesgo import calcular_riesgo

logger = logging.getLogger(__name__)

__all__ = ["calcular_tributario_semanal", "renderizar_tributario_markdown"]


async def calcular_tributario_semanal(hasta: date) -> dict:
    desde      = hasta - timedelta(days=6)
    inicio_mes = date(hasta.year, hasta.month, 1)

    uf = await obtener_uf()
    if uf:
        logger.info(f"UF del día: ${uf:,.2f}")

    async with config.db_pool.acquire() as conn:
        iva    = await calcular_iva(conn, hasta, uf)
        riesgo = await calcular_riesgo(conn, hasta, iva, uf)

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
