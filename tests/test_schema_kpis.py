"""
Regresión: el contexto de schema (text-to-SQL) no debe romperse cuando el config
tiene KPIs por fórmula (clave/nombre/formula) mezclados con los legados (name/sql).
Antes hacía kpi['name'] para todos → KeyError 'name' → tumbaba el tenant al recargar.
"""

from src.schema import _build_schema_text


def test_schema_text_ignora_kpis_formula():
    kpis = [
        {"name": "Ventas 7d", "description": "ventas", "sql": "SELECT 1"},   # legado
        {"clave": "food_cost_pct", "nombre": "Food cost %",                  # por fórmula
         "formula": "costo_ventas / ventas * 100", "unidad": "%"},
    ]
    texto = _build_schema_text(
        tables=[], columns={}, fks={}, annotations={}, kpis=kpis, role_excluded=set())
    assert "Ventas 7d" in texto          # el legado sí aparece
    assert "food_cost_pct" not in texto  # el de fórmula no rompe ni aparece


def test_schema_text_solo_kpis_formula():
    # Solo KPIs por fórmula → no debe romper ni emitir la sección "KPIs importantes".
    kpis = [{"clave": "x", "nombre": "X", "formula": "ventas"}]
    texto = _build_schema_text([], {}, {}, {}, kpis, set())
    assert "KeyError" not in texto and "KPIs importantes" not in texto
