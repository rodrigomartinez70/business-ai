"""
Copiloto Tributario — vertical restaurante (thin wrapper).

El motor es horizontal (`src.finanzas.tributario`). Aquí solo el diferenciador:
`ingresos` = ventas de pedidos pagados.
"""

from datetime import date

from src.finanzas.tributario import (
    calcular_tributario_semanal as _engine,
    renderizar_tributario_markdown,  # noqa: F401 (re-export)
)
from .ingresos import ingresos

__all__ = ["calcular_tributario_semanal", "renderizar_tributario_markdown"]


async def calcular_tributario_semanal(hasta: date) -> dict:
    return await _engine(hasta, ingresos)
