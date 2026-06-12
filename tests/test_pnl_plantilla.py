"""
Tests del P&L por plantilla (F2): resolución de líneas (signo/ref/const/formula) y
validación de la plantilla.
"""

from src.finanzas.pnl_plantilla import _resolver, _necesarias, validar_pnl

PLANTILLA = [
    {"id": "ing",       "etiqueta": "Ingresos",   "tipo": "detalle",  "fuente": "metrica:ventas"},
    {"id": "costo",     "etiqueta": "(-) Costo",  "tipo": "detalle",  "fuente": "metrica:costo_ventas", "signo": -1},
    {"id": "margen",    "etiqueta": "= Margen",   "tipo": "subtotal", "fuente": "ref:ing,costo"},
    {"id": "fc_pct",    "etiqueta": "Food cost %", "tipo": "detalle", "fuente": "formula:costo_ventas / ventas * 100"},
    {"id": "gastos",    "etiqueta": "(-) Gastos", "tipo": "detalle",  "fuente": "const:gastos_fijos", "signo": -1},
    {"id": "resultado", "etiqueta": "= Resultado", "tipo": "total",   "fuente": "ref:margen,gastos"},
]


def test_necesarias():
    assert _necesarias(PLANTILLA) == {"ventas", "costo_ventas"}


def test_resolver_signo_ref_const_formula():
    res = _resolver(PLANTILLA, {"ventas": 1000.0, "costo_ventas": 350.0}, {"gastos_fijos": 200.0})
    assert res["ing"] == 1000.0
    assert res["costo"] == -350.0           # signo -1
    assert res["margen"] == 650.0           # ref suma valores firmados
    assert res["fc_pct"] == 35.0            # formula
    assert res["gastos"] == -200.0          # const con signo
    assert res["resultado"] == 450.0        # ref margen + gastos


def test_validar_ok():
    assert validar_pnl("restaurante", {"plantilla": PLANTILLA}) == []


def test_validar_sin_plantilla():
    assert validar_pnl("restaurante", {}) == []          # sin pnl → ok (usa default)


def test_validar_errores():
    mal = [
        {"id": "x", "fuente": "metrica:inexistente"},     # métrica desconocida
        {"id": "y", "fuente": "ref:futura"},              # ref a línea no anterior
        {"fuente": "metrica:ventas"},                     # falta id
    ]
    errs = validar_pnl("restaurante", {"plantilla": mal})
    assert any("inexistente" in e for e in errs)
    assert any("futura" in e for e in errs)
    assert any("falta 'id'" in e for e in errs)
