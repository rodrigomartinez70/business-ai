"""
Smoke test del vertical restaurante: verifica que todos los módulos importan
(detecta imports relativos/cruzados rotos sin necesitar datos de restaurante).
"""

import importlib
import pytest

MODULOS = [
    "src.verticals.dispatch",
    # Capa horizontal (motor tributario + economía)
    "src.finanzas.economia",
    "src.finanzas.tributario",
    "src.finanzas.tributario.iva",
    "src.finanzas.tributario.riesgo",
    "src.finanzas.tributario.cumplimiento",
    "src.finanzas.tributario.conversacional",
    # Vertical restaurante (delgado)
    "src.verticals.restaurante.insights_prompts",
    "src.verticals.restaurante.dashboard",
    "src.verticals.restaurante.agents.ventas",
    "src.verticals.restaurante.agents.pnl_mensual",
    "src.verticals.restaurante.agents.cierre_diario",
    "src.verticals.restaurante.agents.cash_flow",
    "src.verticals.restaurante.agents.conciliacion",
    "src.verticals.restaurante.agents.tributario",
    "src.verticals.restaurante.agents.tributario.ingresos",
    "src.verticals.restaurante.agents.tributario.conversacional",
]


@pytest.mark.parametrize("mod", MODULOS)
def test_importa(mod):
    importlib.import_module(mod)


def test_tributario_exporta_interfaz():
    trib = importlib.import_module("src.verticals.restaurante.agents.tributario")
    assert hasattr(trib, "calcular_tributario_semanal")
    assert hasattr(trib, "renderizar_tributario_markdown")


def test_dashboard_exporta_interfaz():
    dash = importlib.import_module("src.verticals.restaurante.dashboard")
    assert hasattr(dash, "calcular_dashboard")
    assert hasattr(dash, "renderizar_dashboard_html")


def test_insights_prompts_estructura():
    ip = importlib.import_module("src.verticals.restaurante.insights_prompts")
    assert ip.SYSTEM and isinstance(ip.PROMPTS, dict) and isinstance(ip.RESUMIDORES, dict)
    assert "ventas" in ip.PROMPTS and "ventas" in ip.RESUMIDORES
