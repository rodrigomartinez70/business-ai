"""
Verifica que las guías SQL se arman como genéricas (horizontal) + las del
vertical activo (default hotel cuando no hay tenant).
"""

from src.agent import _guidelines


def test_incluye_genericas_y_del_vertical_hotel():
    g = _guidelines()   # sin tenant en contexto → default hotel
    # genérico
    assert "Patrones genéricos" in g
    assert "YoY" in g
    # específico del hotel
    assert "RevPAR" in g
    # NO debe arrastrar conceptos de otro vertical
    assert "food_cost_pct" not in g
