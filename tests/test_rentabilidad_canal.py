"""
Tests del agente de Rentabilidad por Canal.
"""

import pytest


@pytest.mark.asyncio
async def test_rentabilidad_canal_estructura_json(client, gerente_headers):
    resp = await client.get(
        "/api/agents/rentabilidad-canal?mes=4&anio=2026",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    for campo in ("mes", "año", "mes_nombre", "parcial", "canales",
                  "totales", "insights", "periodo", "ref_anterior"):
        assert campo in data


@pytest.mark.asyncio
async def test_rentabilidad_canal_lista_no_vacia(client, gerente_headers):
    canales = (await client.get(
        "/api/agents/rentabilidad-canal?mes=4&anio=2026",
        headers=gerente_headers,
    )).json()["canales"]
    assert isinstance(canales, list)
    assert len(canales) > 0


@pytest.mark.asyncio
async def test_rentabilidad_canal_campos_numericos(client, gerente_headers):
    canales = (await client.get(
        "/api/agents/rentabilidad-canal?mes=4&anio=2026",
        headers=gerente_headers,
    )).json()["canales"]
    for c in canales:
        for campo in ("comision_pct", "ingresos_brutos", "comision",
                      "ingresos_netos", "adr", "mix_pct"):
            assert isinstance(c[campo], (int, float))
            assert c[campo] >= 0
        assert 0 <= c["tasa_cancel_pct"] <= 100


@pytest.mark.asyncio
async def test_rentabilidad_canal_mix_suma_100(client, gerente_headers):
    canales = (await client.get(
        "/api/agents/rentabilidad-canal?mes=4&anio=2026",
        headers=gerente_headers,
    )).json()["canales"]
    total_mix = sum(c["mix_pct"] for c in canales if c["ingresos_netos"] > 0)
    assert abs(total_mix - 100.0) < 1.0


@pytest.mark.asyncio
async def test_rentabilidad_canal_totales(client, gerente_headers):
    data = (await client.get(
        "/api/agents/rentabilidad-canal?mes=4&anio=2026",
        headers=gerente_headers,
    )).json()
    t = data["totales"]
    canales = data["canales"]
    assert abs(t["ingresos_netos"] - sum(c["ingresos_netos"] for c in canales)) < 1.0
    assert abs(t["reservas"]       - sum(c["reservas_ok"]    for c in canales)) < 1


@pytest.mark.asyncio
async def test_rentabilidad_canal_variaciones_estructura(client, gerente_headers):
    canales = (await client.get(
        "/api/agents/rentabilidad-canal?mes=4&anio=2026",
        headers=gerente_headers,
    )).json()["canales"]
    for c in canales:
        assert "vs_año_anterior" in c
        for campo in ("ingresos_netos", "reservas_ok", "adr", "tasa_cancel_pct"):
            assert campo in c["vs_año_anterior"]


@pytest.mark.asyncio
async def test_rentabilidad_canal_default_mes_anterior(client, gerente_headers):
    resp = await client.get("/api/agents/rentabilidad-canal", headers=gerente_headers)
    assert resp.status_code == 200
    assert resp.json()["mes"] in range(1, 13)


@pytest.mark.asyncio
async def test_rentabilidad_canal_formato_markdown(client, gerente_headers):
    resp = await client.get(
        "/api/agents/rentabilidad-canal?mes=4&anio=2026&formato=markdown",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "Rentabilidad por Canal" in resp.text
    assert "Ranking" in resp.text


@pytest.mark.asyncio
async def test_rentabilidad_canal_requiere_auth(client):
    resp = await client.get("/api/agents/rentabilidad-canal")
    assert resp.status_code == 403
