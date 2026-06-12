"""
Tests del módulo Ventas/Comercial config-driven (KPIs + tablas por fuente).
"""

from src.finanzas import comercial
from src.metricas.registry import catalogo_tablas


def test_tiene_config():
    assert comercial.tiene_config({"ventas": {"kpis": []}})
    assert not comercial.tiene_config({})


def test_fuentes_tabla_registradas():
    rt = {t.nombre for t in catalogo_tablas("restaurante")}
    ht = {t.nombre for t in catalogo_tablas("hotel")}
    assert {"ventas_por_canal", "top_productos"} <= rt
    assert {"hospedaje_por_canal"} <= ht


def test_fmt():
    cfg = {"business": {}}
    assert comercial._fmt(35.0, "pct", cfg) == "35.0%"
    assert comercial._fmt(12, "numero", cfg) == "12"
    assert comercial._fmt(None, "moneda", cfg) == "—"


def test_tabla_html():
    cfg = {"business": {}}
    h = comercial._tabla_html("Por canal",
                              [("canal", "Canal", "texto"), ("n", "N", "numero")],
                              [{"canal": "Salón", "n": 3}], cfg)
    assert "Por canal" in h and "Salón" in h and "<table" in h
    assert comercial._tabla_html("x", [], [], cfg) == ""    # sin filas → vacío


def test_validar_ok():
    ok = {"ventas": {"kpis": [{"clave": "v", "metrica": "ventas"},
                              {"clave": "t", "formula": "ventas / n_pedidos"}],
                     "tablas": [{"titulo": "Por canal", "fuente": "tabla:ventas_por_canal"}]}}
    assert comercial.validar("restaurante", ok) == []


def test_validar_errores():
    errs = comercial.validar("restaurante",
                             {"ventas": {"kpis": [{"metrica": "nope"}],
                                         "tablas": [{"fuente": "tabla:noexiste"}]}})
    assert any("nope" in e for e in errs)
    assert any("noexiste" in e for e in errs)
