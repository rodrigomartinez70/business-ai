"""Test del matcher de conciliación que marca cobradas/pagadas (puro, sin DB)."""

from datetime import date

from src.finanzas.conciliacion import _match_doc


def test_match_doc_monto_y_pago_posterior():
    cands = [{"id": 1, "fecha": date(2026, 4, 1), "monto": 119000.0, "used": False},
             {"id": 2, "fecha": date(2026, 4, 5), "monto": 50000.0, "used": False}]
    m = _match_doc(119000.0, date(2026, 4, 20), cands)      # pago 20/4 ↔ factura 1/4
    assert m and m["id"] == 1 and m["used"] is True
    # la ya usada no se reusa
    assert _match_doc(119000.0, date(2026, 4, 21), cands) is None


def test_match_doc_no_matchea_pago_antes_de_factura():
    cands = [{"id": 3, "fecha": date(2026, 4, 5), "monto": 50000.0, "used": False}]
    assert _match_doc(50000.0, date(2026, 3, 1), cands) is None     # pago antes que la factura


def test_match_doc_fuera_de_tolerancia_de_monto():
    cands = [{"id": 4, "fecha": date(2026, 4, 1), "monto": 119000.0, "used": False}]
    assert _match_doc(60000.0, date(2026, 4, 20), cands) is None
