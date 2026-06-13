"""Tests del normalizador del RCV del SII (puros, sin red ni DB)."""

from datetime import date

import pytest

from src.finanzas.rcv import normalizar_rcv

# RCV Compras (formato portal SII, separador ';').
_COMPRAS = (
    "Nro;Tipo Doc;Tipo Compra;RUT Proveedor;Razon Social;Folio;Fecha Docto;"
    "Monto Exento;Monto Neto;Monto IVA Recuperable;Monto Total\n"
    "1;33;Del Giro;76.111.222-3;Distribuidora Sur SpA;1001;15/04/2026;0;100.000;19.000;119.000\n"
    "2;61;Del Giro;76.111.222-3;Distribuidora Sur SpA;55;20/04/2026;0;10.000;1.900;11.900\n"
    "TOTALES;;;;;;;0;110.000;20.900;130.900\n"
)

# RCV Ventas.
_VENTAS = (
    "Nro;Tipo Doc;Tipo Venta;Rut cliente;Razon Social;Folio;Fecha Docto;"
    "Monto Exento;Monto Neto;Monto IVA;Monto total\n"
    "1;33;Del Giro;77.999.888-1;Cliente Uno Ltda;2001;10/04/2026;0;500.000;95.000;595.000\n"
    "2;39;Del Giro;66.555.444-2;Consumidor Final;2002;11/04/2026;0;50.000;9.500;59.500\n"
)


def test_compras_detecta_clase_y_parsea():
    res = normalizar_rcv(_COMPRAS.encode("utf-8"))
    assert res["meta"]["clase"] == "compra"
    assert res["meta"]["total"] == 2          # la fila TOTALES (sin folio/fecha) se descarta
    d0 = res["documentos"][0]
    assert d0["tipo"] == "factura"
    assert d0["numero_documento"] == "1001"
    assert d0["rut_contraparte"] == "76.111.222-3"
    assert d0["fecha"] == date(2026, 4, 15)
    assert d0["monto_neto"] == 100000.0 and d0["monto_iva"] == 19000.0
    assert res["documentos"][1]["tipo"] == "nota_credito"   # tipo doc 61
    assert res["meta"]["total_iva"] == 20900.0


def test_ventas_detecta_clase_y_tipos():
    res = normalizar_rcv(_VENTAS.encode("utf-8"))
    assert res["meta"]["clase"] == "venta"
    assert res["meta"]["total"] == 2
    assert res["documentos"][0]["tipo"] == "factura"        # 33
    assert res["documentos"][1]["tipo"] == "boleta"         # 39
    assert res["documentos"][0]["proveedor"] == "Cliente Uno Ltda"   # contraparte
    assert res["meta"]["total_iva"] == 104500.0


def test_rcv_sin_clase_detectable_falla():
    csv = ("Nro;Tipo Doc;Folio;Fecha Docto;Monto Neto;Monto IVA;Monto Total\n"
           "1;33;1;10/04/2026;100;19;119\n")
    with pytest.raises(ValueError):
        normalizar_rcv(csv.encode("utf-8"))


def test_rcv_vacio_falla():
    with pytest.raises(ValueError):
        normalizar_rcv(b"")
