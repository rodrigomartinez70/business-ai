"""Tests del conector Toteat (puros: chunking, parseo, mock — sin red ni DB)."""

from datetime import date

import pytest

from src.integraciones import toteat


def test_chunks_respeta_maximo_15_dias_y_cubre_el_rango():
    desde, hasta = date(2026, 1, 1), date(2026, 2, 10)  # 41 días
    tramos = list(toteat._chunks(desde, hasta))
    # cada tramo ≤ 15 días
    for ini, fin in tramos:
        assert (fin - ini).days <= 14
    # contiguos y cubren todo el rango
    assert tramos[0][0] == desde
    assert tramos[-1][1] == hasta
    for (a_ini, a_fin), (b_ini, _b_fin) in zip(tramos, tramos[1:]):
        assert (b_ini - a_fin).days == 1


def test_chunk_unico_si_cabe_en_15_dias():
    tramos = list(toteat._chunks(date(2026, 5, 1), date(2026, 5, 10)))
    assert tramos == [(date(2026, 5, 1), date(2026, 5, 10))]


def test_parse_producto():
    raw = {"id": 9001, "name": "Pizza Margarita", "price": 10990, "referencePrice": None,
           "category": "Pizzas", "categoryId": 101, "localCode": "P001", "isModifier": False}
    p = toteat._parse_producto(raw)
    assert p["id_externo"] == "9001"
    assert p["nombre"] == "Pizza Margarita"
    assert p["precio"] == 10990.0
    assert p["categoria"] == "Pizzas"
    assert p["es_modificador"] is False


def test_parse_venta_extrae_lineas_y_pagos():
    raw = {
        "orderId": 1089433731487782, "orderReference": "102030",
        "closeDate": "2026-05-10T20:15:00", "orderStatus": "CLOSED",
        "tableId": 7, "channel": "salon", "total": 21980,
        "line": [{"productName": "Hamburguesa", "productCode": "ham", "quantity": 2,
                  "price": 8990, "total": 17980}],
        "payments": [{"paymentMethodId": 2000, "amount": 21980, "fiscalType": "BOL"}],
    }
    v = toteat._parse_venta(raw)
    assert v["order_id"] == "1089433731487782"
    assert v["fecha"] == "2026-05-10T20:15:00"
    assert v["total"] == 21980.0
    assert len(v["lineas"]) == 1 and v["lineas"][0]["cantidad"] == 2.0
    assert v["pagos"][0]["medio"] == "Tarjeta Crédito"  # 2000 → mapeado


def test_medios_pago_mapea_ids_conocidos():
    assert toteat.MEDIOS_PAGO[1000] == "Efectivo"
    assert toteat.MEDIOS_PAGO[3000] == "Tarjeta Débito"


@pytest.mark.asyncio
async def test_obtener_datos_mock_produce_estructuras_validas():
    data = await toteat.obtener_datos(None, date(2026, 5, 1), date(2026, 5, 3), mock=True)
    assert data["productos"] and data["ventas"]
    # productos normalizados
    assert all("nombre" in p and "precio" in p for p in data["productos"])
    # ventas con líneas y pagos
    v = data["ventas"][0]
    assert v["lineas"] and v["pagos"]
    assert v["total"] > 0
