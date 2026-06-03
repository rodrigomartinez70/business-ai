"""Conversacional tributario — restaurante (thin wrapper sobre el motor horizontal)."""

from src.finanzas.tributario.conversacional import responder_tributario as _resp
from . import calcular_tributario_semanal


async def responder_tributario(pregunta: str, historial: list[dict] | None = None) -> str:
    return await _resp(pregunta, historial, calcular_tributario_semanal)
