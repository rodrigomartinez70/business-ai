"""
Dispatch por vertical — resuelve el módulo correcto según el tenant activo.

Las features cross-cutting (dashboard semanal, copiloto tributario, conciliación,
conversacional) existen por vertical en src/verticals/<vertical>/. Este módulo
devuelve el módulo del vertical del tenant en curso, con 'hotel' como default.
"""

import importlib

from ..tenant import get_tenant_or_none


def _vertical() -> str:
    ctx = get_tenant_or_none()
    return ctx.vertical if (ctx and ctx.vertical) else "hotel"


def dashboard():
    return importlib.import_module(f"src.verticals.{_vertical()}.dashboard")


def tributario():
    return importlib.import_module(f"src.verticals.{_vertical()}.agents.tributario")


def conciliacion():
    return importlib.import_module(f"src.verticals.{_vertical()}.agents.conciliacion")


def conversacional():
    return importlib.import_module(f"src.verticals.{_vertical()}.agents.tributario.conversacional")
