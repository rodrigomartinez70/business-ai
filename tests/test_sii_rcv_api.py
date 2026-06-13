"""Tests del mapeo de la respuesta RCV del SII → documento (Fase B paso 2), sin red."""

from datetime import date

import pytest

pytest.importorskip("httpx")

from src.integraciones import sii_rcv_api


def test_mapear_compra_recibido():
    item = {"detTipoDoc": "33", "detNroDoc": "1001", "detRutDoc": "76111222",
            "detDvDoc": "3", "detRznSoc": "Distribuidora Sur SpA", "detFchDoc": "15/04/2026",
            "detMntNeto": "100.000", "detMntIVA": "19.000", "detMntTotal": "119.000"}
    d = sii_rcv_api._mapear_item(item, "COMPRA")
    assert d["clase"] == "compra" and d["tipo"] == "factura"
    assert d["numero_documento"] == "1001" and d["rut_contraparte"] == "76111222-3"
    assert d["fecha"] == date(2026, 4, 15)
    assert d["monto_iva"] == 19000.0 and d["monto_total"] == 119000.0


def test_mapear_venta_nota_credito_nombres_alternativos():
    # Usa nombres de campo alternativos (el SII varía entre versiones).
    item = {"tipoDoc": "61", "folio": "55", "rut": "77999888", "dv": "1",
            "razonSocial": "Cliente Uno", "fchDoc": "2026-04-20",
            "mntNeto": "10000", "mntIVA": "1900", "mntTotal": "11900"}
    d = sii_rcv_api._mapear_item(item, "VENTA")
    assert d["clase"] == "venta" and d["tipo"] == "nota_credito"
    assert d["numero_documento"] == "55" and d["monto_iva"] == 1900.0


def test_extraer_detalle_tolerante():
    assert sii_rcv_api._extraer_detalle({"data": {"detalleCompra": [{"a": 1}]}}) == [{"a": 1}]
    assert sii_rcv_api._extraer_detalle({"data": {"detalle": [{"b": 2}]}}) == [{"b": 2}]
    assert sii_rcv_api._extraer_detalle({"data": [{"c": 3}]}) == [{"c": 3}]
    assert sii_rcv_api._extraer_detalle({}) == []


def test_rut_partes():
    assert sii_rcv_api._rut_partes("76.111.222-3") == ("76111222", "3")
    assert sii_rcv_api._rut_partes("761112223") == ("76111222", "3")
