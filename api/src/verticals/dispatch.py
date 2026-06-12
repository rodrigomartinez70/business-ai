"""
Dispatch por vertical — resuelve el módulo correcto según el tenant activo,
respaldado por el contrato de vertical (registry.py).

Las features cross-cutting (dashboard semanal, copiloto tributario, conversacional)
existen por vertical; la conciliación es horizontal (sin diferenciador).
"""

import importlib

from ..tenant import get_tenant_or_none
from . import registry

# Verticales con dashboard POS propio. El resto (comercial/genérico) usa el
# dashboard horizontal config-driven (ver doc/design-packs.md, P3).
_POS_VERTICALS = registry.VERTICALS


def _vertical() -> str:
    ctx = get_tenant_or_none()
    return ctx.vertical if (ctx and ctx.vertical) else "hotel"


def dashboard():
    v = _vertical()
    if v in _POS_VERTICALS:
        return registry.cargar(v).dashboard
    from ..finanzas import dashboard_generico
    return dashboard_generico


def tributario():
    return registry.cargar(_vertical()).tributario


def conversacional():
    return registry.cargar(_vertical()).conversacional


def pnl():
    return importlib.import_module(f"src.verticals.{_vertical()}.agents.pnl")


def conciliacion():
    # Conciliación es horizontal (no tiene diferenciador por vertical).
    return importlib.import_module("src.finanzas.conciliacion")
