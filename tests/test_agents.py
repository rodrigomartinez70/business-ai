"""
Tests del Agente 8 — Indicadores y Alertas Tempranas.

No dependen de valores específicos (los datos del seed pueden no estar en el
período actual), pero sí verifican la estructura y el comportamiento del endpoint.
"""

import pytest


EXPECTED_KPI_KEYS = {
    "fecha_inicio", "fecha_fin", "periodo_dias",
    "hab_activas", "reservas_checkin", "ocupacion_pct",
    "adr", "revpar",
    "ingresos_total", "gastos_total", "gop",
    "quema_diaria", "pagos_pendientes",
}

EXPECTED_RESPONSE_KEYS = {"alertas_activas", "estado_general", "kpis", "alertas", "reporte_md"}
ESTADOS_VALIDOS = {"ok", "alerta", "critico"}


@pytest.mark.asyncio
async def test_alertas_estructura_json(client, gerente_headers):
    resp = await client.get("/api/agents/alertas", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert EXPECTED_RESPONSE_KEYS == set(data.keys())
    assert data["estado_general"] in ESTADOS_VALIDOS
    assert isinstance(data["alertas_activas"], int)
    assert isinstance(data["alertas"], list)


@pytest.mark.asyncio
async def test_alertas_kpis_tienen_todas_las_claves(client, gerente_headers):
    resp = await client.get("/api/agents/alertas", headers=gerente_headers)
    kpis = resp.json()["kpis"]
    assert EXPECTED_KPI_KEYS == set(kpis.keys())


@pytest.mark.asyncio
async def test_alertas_kpis_son_numericos(client, gerente_headers):
    kpis = (await client.get("/api/agents/alertas", headers=gerente_headers)).json()["kpis"]
    for campo in ("ocupacion_pct", "adr", "revpar", "ingresos_total", "gastos_total", "gop", "quema_diaria"):
        assert isinstance(kpis[campo], (int, float)), f"{campo} no es numérico"
    assert isinstance(kpis["hab_activas"], int)


@pytest.mark.asyncio
async def test_alertas_formato_markdown(client, gerente_headers):
    resp = await client.get("/api/agents/alertas?formato=markdown", headers=gerente_headers)
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "KPIs" in resp.text
    assert "Ocupación" in resp.text


@pytest.mark.asyncio
async def test_alertas_formato_discord_payload(client, gerente_headers):
    resp = await client.get("/api/agents/alertas?formato=discord_payload", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert len(data["content"]) <= 1900  # límite Discord


@pytest.mark.asyncio
async def test_alertas_periodo_personalizado(client, gerente_headers):
    resp = await client.get("/api/agents/alertas?periodo_dias=30", headers=gerente_headers)
    assert resp.status_code == 200
    assert resp.json()["kpis"]["periodo_dias"] == 30


@pytest.mark.asyncio
async def test_alertas_periodo_invalido(client, gerente_headers):
    """periodo_dias=0 está fuera del rango ge=1."""
    resp = await client.get("/api/agents/alertas?periodo_dias=0", headers=gerente_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_alertas_consistencia_gop(client, gerente_headers):
    """GOP debe ser siempre ingresos - gastos."""
    kpis = (await client.get("/api/agents/alertas", headers=gerente_headers)).json()["kpis"]
    gop_calculado = round(kpis["ingresos_total"] - kpis["gastos_total"], 2)
    assert abs(kpis["gop"] - gop_calculado) < 0.01
