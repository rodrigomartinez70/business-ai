"""
Tests del agente de Indicadores y Alertas Tempranas.

Verifican la estructura y comportamiento del endpoint sin asumir
KPIs específicos de negocio — el contenido depende de config.yaml.
"""

import pytest


EXPECTED_RESPONSE_KEYS = {"alertas_activas", "estado_general", "kpis", "alertas", "reporte_md"}
ESTADOS_VALIDOS        = {"ok", "alerta", "critico"}
KPI_KEYS_MINIMAS       = {"name", "valor", "unidad"}


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
async def test_alertas_kpis_es_lista_de_dicts(client, gerente_headers):
    kpis = (await client.get("/api/agents/alertas", headers=gerente_headers)).json()["kpis"]
    assert isinstance(kpis, list)
    for kpi in kpis:
        assert KPI_KEYS_MINIMAS.issubset(kpi.keys()), f"KPI sin claves mínimas: {kpi}"
        assert isinstance(kpi["name"], str)


@pytest.mark.asyncio
async def test_alertas_kpis_valores_numericos_o_none(client, gerente_headers):
    kpis = (await client.get("/api/agents/alertas", headers=gerente_headers)).json()["kpis"]
    for kpi in kpis:
        assert kpi["valor"] is None or isinstance(kpi["valor"], (int, float)), \
            f"KPI '{kpi['name']}' tiene valor no numérico: {kpi['valor']}"


@pytest.mark.asyncio
async def test_alertas_alertas_tienen_estructura_correcta(client, gerente_headers):
    alertas = (await client.get("/api/agents/alertas", headers=gerente_headers)).json()["alertas"]
    for a in alertas:
        assert {"kpi", "valor", "umbral", "nivel"}.issubset(a.keys())
        assert a["nivel"] in {"alerta", "critico"}


@pytest.mark.asyncio
async def test_alertas_formato_markdown(client, gerente_headers):
    resp = await client.get("/api/agents/alertas?formato=markdown", headers=gerente_headers)
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "KPIs" in resp.text


@pytest.mark.asyncio
async def test_alertas_formato_discord_payload(client, gerente_headers):
    resp = await client.get("/api/agents/alertas?formato=discord_payload", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "embeds" in data
    assert isinstance(data["embeds"], list)
    assert len(data["embeds"]) == 1
    embed = data["embeds"][0]
    assert "title" in embed
    assert "color" in embed
    assert "fields" in embed
    assert isinstance(embed["fields"], list)


@pytest.mark.asyncio
async def test_alertas_periodo_personalizado(client, gerente_headers):
    resp = await client.get("/api/agents/alertas?periodo_dias=30", headers=gerente_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json()["kpis"], list)


@pytest.mark.asyncio
async def test_alertas_periodo_invalido(client, gerente_headers):
    """periodo_dias=0 está fuera del rango ge=1."""
    resp = await client.get("/api/agents/alertas?periodo_dias=0", headers=gerente_headers)
    assert resp.status_code == 422
