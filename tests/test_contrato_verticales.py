"""
Enforce del contrato de vertical: cada vertical registrado debe exponer los
entrypoints y archivos requeridos (registry.cargar valida o lanza).
"""

import pytest

from src.verticals import registry


@pytest.mark.parametrize("nombre", registry.VERTICALS)
def test_vertical_cumple_contrato(nombre):
    v = registry.cargar(nombre)   # lanza RuntimeError si incumple el contrato
    assert v.nombre == nombre
    assert callable(v.dashboard.calcular_dashboard)
    assert callable(v.dashboard.renderizar_dashboard_html)
    assert callable(v.tributario.calcular_tributario_semanal)
    assert callable(v.tributario.renderizar_tributario_markdown)
    assert callable(v.conversacional.responder_tributario)
    assert v.insights_prompts.SYSTEM
    assert isinstance(v.insights_prompts.PROMPTS, dict)
    assert isinstance(v.insights_prompts.RESUMIDORES, dict)


def test_incumplimiento_se_detecta():
    """Un vertical inexistente o incompleto falla la carga."""
    with pytest.raises(Exception):
        registry.cargar("vertical_que_no_existe")
