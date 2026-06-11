"""
Tests de la capa semántica (F0/F1): evaluador de fórmulas seguro, catálogo de
métricas y validación de KPIs por fórmula.
"""

import pytest

from src.metricas import formula
from src.metricas.registry import catalogo
from src.metricas import kpis as mk


# ── Evaluador de fórmulas (seguro) ──────────────────────────────────────

def test_formula_aritmetica():
    assert formula.evaluar("costo / ventas * 100", {"costo": 33, "ventas": 100}) == 33.0
    assert formula.evaluar("(a - b) / a * 100", {"a": 100, "b": 60}) == 40.0
    assert formula.evaluar("max(a, 5) + min(b, 2)", {"a": 3, "b": 9}) == 7.0


def test_formula_div_cero_segura():
    assert formula.evaluar("a / b", {"a": 10, "b": 0}) == 0.0


def test_formula_nombres_referenciados():
    assert formula.nombres_referenciados("costo_ventas / ventas * 100") == {"costo_ventas", "ventas"}
    assert formula.nombres_referenciados("max(a, 5)") == {"a"}    # excluye la función


@pytest.mark.parametrize("expr", [
    "__import__('os')", "a.b", "open('x')", "a if b else c", "[1,2,3]", "lambda: 1",
])
def test_formula_bloquea_codigo(expr):
    with pytest.raises(formula.FormulaError):
        formula.evaluar(expr, {"a": 1, "b": 1, "c": 1})


# ── Catálogo de métricas ────────────────────────────────────────────────

def test_catalogo_restaurante():
    nombres = {m.nombre for m in catalogo("restaurante")}
    assert {"ventas", "costo_ventas", "n_pedidos", "ingresos"} <= nombres   # vertical
    assert {"cobros", "gastos_total"} <= nombres                            # horizontales


def test_catalogo_hotel():
    nombres = {m.nombre for m in catalogo("hotel")}
    assert {"hospedaje", "noches", "consumos", "ingresos"} <= nombres


# ── Validación de KPIs ──────────────────────────────────────────────────

def test_validar_kpi_ok():
    kpis = [{"clave": "food_cost_pct", "nombre": "FC%",
             "formula": "costo_ventas / ventas * 100", "unidad": "%", "umbral_max": 35}]
    assert mk.validar("restaurante", kpis) == []


def test_validar_kpi_errores():
    kpis = [{"clave": "x", "formula": "inexistente / ventas"},   # métrica desconocida
            {"nombre": "sin clave", "metrica": "ventas"}]         # falta clave
    errores = mk.validar("restaurante", kpis)
    assert any("inexistente" in e for e in errores)
    assert any("falta 'clave'" in e for e in errores)


def test_validar_ignora_kpis_sql():
    # Los KPIs legados (con 'sql') no los toca este validador.
    assert mk.validar("restaurante", [{"name": "x", "sql": "SELECT 1"}]) == []
