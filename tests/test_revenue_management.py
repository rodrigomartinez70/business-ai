"""
Tests del agente de Revenue Management.
"""

import pytest


@pytest.mark.asyncio
async def test_revenue_estructura_json(client, gerente_headers):
    resp = await client.get("/api/agents/revenue-management", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    for campo in ("fecha", "hab_activas", "snapshot", "historico",
                  "proyeccion", "canales", "oportunidades_precio"):
        assert campo in data


@pytest.mark.asyncio
async def test_revenue_snapshot_estructura(client, gerente_headers):
    s = (await client.get("/api/agents/revenue-management", headers=gerente_headers)).json()["snapshot"]
    for campo in ("ocupadas", "ocupacion_pct", "adr", "revpar", "checkins_hoy"):
        assert campo in s
    assert 0 <= s["ocupacion_pct"] <= 100
    assert s["ocupadas"] >= 0
    assert s["revpar"] >= 0


@pytest.mark.asyncio
async def test_revenue_historico_estructura(client, gerente_headers):
    h = (await client.get("/api/agents/revenue-management", headers=gerente_headers)).json()["historico"]
    for periodo in ("7d", "30d"):
        assert periodo in h
        for campo in ("adr", "revpar", "ocupacion_pct"):
            assert campo in h[periodo]


@pytest.mark.asyncio
async def test_revenue_proyeccion_horizon(client, gerente_headers):
    data = (await client.get(
        "/api/agents/revenue-management?horizon_dias=14",
        headers=gerente_headers,
    )).json()
    proy = data["proyeccion"]
    assert proy["horizon_dias"] == 14
    assert len(proy["calendario"]) == 14
    for r in proy["calendario"]:
        assert "fecha" in r
        assert "ocupacion_pct" in r
        assert 0 <= r["ocupacion_pct"] <= 100


@pytest.mark.asyncio
async def test_revenue_canales_estructura(client, gerente_headers):
    canales = (await client.get("/api/agents/revenue-management", headers=gerente_headers)).json()["canales"]
    for c in canales:
        assert "canal" in c
        assert "ingresos_netos" in c
        assert c["ingresos_netos"] >= 0


@pytest.mark.asyncio
async def test_revenue_oportunidades_estructura(client, gerente_headers):
    opors = (await client.get("/api/agents/revenue-management", headers=gerente_headers)).json()["oportunidades_precio"]
    for o in opors:
        assert "fecha" in o
        assert "ocupacion_pct" in o
        assert "adr_actual" in o
        assert "diferencia_pct" in o
        assert o["diferencia_pct"] > 0


@pytest.mark.asyncio
async def test_revenue_formato_markdown(client, gerente_headers):
    resp = await client.get(
        "/api/agents/revenue-management?formato=markdown",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "Revenue Management" in resp.text
    assert "RevPAR" in resp.text


@pytest.mark.asyncio
async def test_revenue_formato_discord_payload(client, gerente_headers):
    resp = await client.get(
        "/api/agents/revenue-management?formato=discord_payload",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "embeds" in data
    embed = data["embeds"][0]
    assert "title" in embed
    assert "color" in embed
    assert len(embed["fields"]) >= 3


@pytest.mark.asyncio
async def test_revenue_requiere_auth(client):
    resp = await client.get("/api/agents/revenue-management")
    assert resp.status_code == 403
