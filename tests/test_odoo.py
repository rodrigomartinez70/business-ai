"""Tests del conector Odoo (puros: parseo + mock, sin red ni DB)."""
from datetime import date
import pytest
from src.integraciones import odoo


def test_m2o_many2one():
    assert odoo._m2o([5, "Cliente X"]) == "Cliente X"
    assert odoo._m2o(False) is None
    assert odoo._m2o(None) is None


def test_parse_factura():
    r = {"id": 5001, "move_type": "out_invoice", "name": "INV/2026/0001",
         "invoice_date": "2026-06-03", "partner_id": [10, "Comercial Andes SpA"],
         "amount_untaxed": 100000, "amount_tax": 19000, "amount_total": 119000,
         "state": "posted", "payment_state": "paid"}
    f = odoo._parse_factura(r)
    assert f["id_externo"] == "5001"
    assert f["tipo"] == "out_invoice" and f["tipo_label"] == "Factura de venta"
    assert f["partner"] == "Comercial Andes SpA"
    assert f["monto_total"] == 119000.0


def test_parse_producto_y_cliente():
    p = odoo._parse_producto({"id": 1, "name": "Producto A", "default_code": "P001",
                              "list_price": 8990, "standard_price": 3200, "categ_id": [1, "Productos"]})
    assert p["precio"] == 8990.0 and p["costo"] == 3200.0 and p["categoria"] == "Productos"
    c = odoo._parse_cliente({"id": 10, "name": "X", "vat": "76123-4", "customer_rank": 1, "supplier_rank": 0})
    assert c["es_cliente"] is True and c["es_proveedor"] is False


@pytest.mark.asyncio
async def test_obtener_datos_mock():
    d = await odoo.obtener_datos(None, date(2026, 6, 1), date(2026, 6, 30), mock=True)
    assert d["facturas"] and d["productos"] and d["clientes"]
    assert all("monto_total" in f for f in d["facturas"])
    assert all("precio" in p and "costo" in p for p in d["productos"])
