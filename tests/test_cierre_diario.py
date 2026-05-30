"""
Tests del agente de Cierre Diario.

Verifican la estructura del endpoint sin asumir valores específicos
de negocio — el contenido depende de los datos generados en la DB de test.
"""

import pytest
from datetime import date


@pytest.mark.asyncio
async def test_cierre_estructura_json(client, gerente_headers):
    resp = await client.get("/api/agents/cierre-diario", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "fecha" in data
    assert "ocupacion" in data
    assert "movimientos" in data
    assert "ingresos" in data
    assert "cobros" in data
    assert "gastos" in data
    assert "resumen" in data
    assert "comisiones_ota" in data


@pytest.mark.asyncio
async def test_cierre_ocupacion_estructura(client, gerente_headers):
    data = (await client.get("/api/agents/cierre-diario", headers=gerente_headers)).json()
    ocu = data["ocupacion"]
    assert "en_casa" in ocu
    assert "total_habitaciones" in ocu
    assert "pct_ocupacion" in ocu
    assert isinstance(ocu["en_casa"], int)
    assert ocu["total_habitaciones"] > 0
    assert 0 <= ocu["pct_ocupacion"] <= 100


@pytest.mark.asyncio
async def test_cierre_movimientos_estructura(client, gerente_headers):
    data = (await client.get("/api/agents/cierre-diario", headers=gerente_headers)).json()
    mov = data["movimientos"]
    for campo in ("checkins", "checkouts", "reservas_nuevas", "cancelaciones"):
        assert campo in mov
        assert isinstance(mov[campo], int)
        assert mov[campo] >= 0


@pytest.mark.asyncio
async def test_cierre_ingresos_son_numericos(client, gerente_headers):
    data = (await client.get("/api/agents/cierre-diario", headers=gerente_headers)).json()
    ing = data["ingresos"]
    for campo in ("hospedaje", "frigobar", "servicios", "total"):
        assert campo in ing
        assert isinstance(ing[campo], (int, float))
        assert ing[campo] >= 0
    assert abs(ing["total"] - (ing["hospedaje"] + ing["frigobar"] + ing["servicios"])) < 0.01


@pytest.mark.asyncio
async def test_cierre_cobros_estructura(client, gerente_headers):
    data = (await client.get("/api/agents/cierre-diario", headers=gerente_headers)).json()
    cob = data["cobros"]
    assert "cobrado" in cob
    assert "pendiente" in cob
    assert "n_pagos" in cob
    assert "por_metodo" in cob
    for metodo in ("efectivo", "tarjeta", "transferencia"):
        assert metodo in cob["por_metodo"]


@pytest.mark.asyncio
async def test_cierre_resumen_gop(client, gerente_headers):
    data = (await client.get("/api/agents/cierre-diario", headers=gerente_headers)).json()
    r = data["resumen"]
    assert "gop_devengado"  in r
    assert "resultado_caja" in r
    assert "gop_estado"     in r
    assert r["gop_estado"] in ("positivo", "negativo")
    assert abs(r["gop_devengado"]  - (r["total_ingresos"] - r["total_gastos"])) < 0.01
    assert abs(r["resultado_caja"] - (r["total_cobrado"]  - r["total_gastos"])) < 0.01


@pytest.mark.asyncio
async def test_cierre_fecha_personalizada(client, gerente_headers):
    resp = await client.get(
        "/api/agents/cierre-diario?fecha=2025-01-15",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["fecha"] == "2025-01-15"


@pytest.mark.asyncio
async def test_cierre_formato_markdown(client, gerente_headers):
    resp = await client.get(
        "/api/agents/cierre-diario?formato=markdown",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "Cierre Diario" in resp.text
    assert "GOP" in resp.text


@pytest.mark.asyncio
async def test_cierre_formato_discord_payload(client, gerente_headers):
    resp = await client.get(
        "/api/agents/cierre-diario?formato=discord_payload",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "embeds" in data
    embed = data["embeds"][0]
    assert "title" in embed
    assert "color" in embed
    assert "fields" in embed
    assert len(embed["fields"]) == 6


@pytest.mark.asyncio
async def test_cierre_requiere_auth(client):
    resp = await client.get("/api/agents/cierre-diario")
    assert resp.status_code == 403
