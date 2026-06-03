"""
Copiloto Tributario — vertical hotel (thin wrapper).

El motor (IVA/F29, Cumplimiento, Riesgo, conversacional, calendario) es
horizontal en `src.finanzas.tributario`. Aquí solo se aporta el diferenciador
del vertical: `ingresos` (qué cuenta como ingreso afecto).
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
