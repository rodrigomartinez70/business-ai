"""Tests del conector Defontana (mock, sin red ni DB)."""
from datetime import date
import pytest
from src.integraciones import defontana


def test_tipos_doc():
    assert "factura_venta" in defontana.TIPOS_DOC


@pytest.mark.asyncio
async def test_obtener_datos_mock():
    d = await defontana.obtener_datos(None, date(2026, 6, 1), date(2026, 6, 30), mock=True)
    assert d["facturas"] and d["ventas"] and d["productos"] and d["clientes"]
    for f in d["facturas"]:
        assert f["monto_total"] == f["monto_neto"] + f["monto_iva"]
        assert f["tipo"] in defontana.TIPOS_DOC
    assert all("precio" in p and "costo" in p for p in d["productos"])


def test_mock_determinista_por_dia():
    a = defontana._mock(date(2026, 6, 1), date(2026, 6, 30))
    b = defontana._mock(date(2026, 6, 1), date(2026, 6, 30))
    assert [f["id_externo"] for f in a["facturas"]] == [f["id_externo"] for f in b["facturas"]]
