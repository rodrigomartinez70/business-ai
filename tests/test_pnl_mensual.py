"""
Tests del agente de P&L Mensual.
"""

import pytest


@pytest.mark.asyncio
async def test_pnl_estructura_json(client, gerente_headers):
    resp = await client.get("/api/agents/pnl-mensual?mes=4&año=2026", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    for campo in ("mes", "año", "mes_nombre", "actual", "anterior", "año_pasado", "comparativas"):
        assert campo in data


@pytest.mark.asyncio
async def test_pnl_periodo_correcto(client, gerente_headers):
    data = (await client.get("/api/agents/pnl-mensual?mes=4&año=2026", headers=gerente_headers)).json()
    assert data["mes"] == 4
    assert data["año"] == 2026
    assert data["actual"]["periodo"]["inicio"] == "2026-04-01"
    assert data["actual"]["periodo"]["fin"]    == "2026-04-30"
    assert data["anterior"]["periodo"]["inicio"] == "2026-03-01"
    assert data["año_pasado"]["periodo"]["inicio"] == "2025-04-01"


@pytest.mark.asyncio
async def test_pnl_ingresos_numericos(client, gerente_headers):
    ing = (await client.get("/api/agents/pnl-mensual?mes=4&año=2026", headers=gerente_headers)).json()["actual"]["ingresos"]
    for campo in ("hospedaje", "frigobar", "servicios", "total", "cobros_caja"):
        assert isinstance(ing[campo], (int, float))
        assert ing[campo] >= 0
    assert abs(ing["total"] - (ing["hospedaje"] + ing["frigobar"] + ing["servicios"])) < 0.01


@pytest.mark.asyncio
async def test_pnl_resultado_gop(client, gerente_headers):
    data = (await client.get("/api/agents/pnl-mensual?mes=4&año=2026", headers=gerente_headers)).json()
    res = data["actual"]["resultado"]
    ing = data["actual"]["ingresos"]["total"]
    gas = data["actual"]["gastos"]["total"]
    assert abs(res["gop"] - (ing - gas)) < 0.01
    assert res["estado"] in ("positivo", "negativo")


@pytest.mark.asyncio
async def test_pnl_metricas_rango(client, gerente_headers):
    met = (await client.get("/api/agents/pnl-mensual?mes=4&año=2026", headers=gerente_headers)).json()["actual"]["metricas"]
    assert met["hab_activas"] > 0
    assert met["cap_noches"]  > 0
    if met["ocupacion_pct"] is not None:
        assert 0 <= met["ocupacion_pct"] <= 100


@pytest.mark.asyncio
async def test_pnl_comparativas_estructura(client, gerente_headers):
    comp = (await client.get("/api/agents/pnl-mensual?mes=4&año=2026", headers=gerente_headers)).json()["comparativas"]
    for key in ("ingresos_total", "gop", "ocupacion", "revpar"):
        assert key in comp
        assert "vs_mes_anterior" in comp[key]
        assert "vs_año_anterior" in comp[key]


@pytest.mark.asyncio
async def test_pnl_default_mes_anterior(client, gerente_headers):
    """Sin parámetros devuelve el mes anterior al actual."""
    resp = await client.get("/api/agents/pnl-mensual", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["mes"] in range(1, 13)
    assert data["año"] >= 2025


@pytest.mark.asyncio
async def test_pnl_formato_markdown(client, gerente_headers):
    resp = await client.get("/api/agents/pnl-mensual?mes=4&año=2026&formato=markdown", headers=gerente_headers)
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "P&L Mensual" in resp.text
    assert "GOP" in resp.text
    assert "RevPAR" in resp.text


@pytest.mark.asyncio
async def test_pnl_formato_discord_payload(client, gerente_headers):
    resp = await client.get("/api/agents/pnl-mensual?mes=4&año=2026&formato=discord_payload", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "embeds" in data
    embed = data["embeds"][0]
    assert "title" in embed
    assert "color" in embed
    assert len(embed["fields"]) == 6


@pytest.mark.asyncio
async def test_pnl_requiere_auth(client):
    resp = await client.get("/api/agents/pnl-mensual")
    assert resp.status_code == 403
