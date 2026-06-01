"""
Tests del agente de Cash Flow.
"""

import pytest


@pytest.mark.asyncio
async def test_cash_flow_estructura_json(client, gerente_headers):
    resp = await client.get("/api/agents/cash-flow", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    for campo in ("fecha", "horizon_semanas", "semaforo", "resumen",
                  "semanas", "gastos_por_categoria"):
        assert campo in data


@pytest.mark.asyncio
async def test_cash_flow_semaforo_valido(client, gerente_headers):
    data = (await client.get("/api/agents/cash-flow", headers=gerente_headers)).json()
    assert data["semaforo"] in ("ok", "alerta", "critico")


@pytest.mark.asyncio
async def test_cash_flow_semanas_count(client, gerente_headers):
    data = (await client.get("/api/agents/cash-flow", headers=gerente_headers)).json()
    assert len(data["semanas"]) == data["horizon_semanas"]


@pytest.mark.asyncio
async def test_cash_flow_semanas_estructura(client, gerente_headers):
    semanas = (await client.get("/api/agents/cash-flow", headers=gerente_headers)).json()["semanas"]
    for s in semanas:
        for campo in ("semana_inicio", "semana_fin", "ingresos",
                      "gastos_est", "flujo_neto", "acumulado"):
            assert campo in s
        assert isinstance(s["ingresos"],   (int, float))
        assert isinstance(s["gastos_est"], (int, float))


@pytest.mark.asyncio
async def test_cash_flow_acumulado_consistente(client, gerente_headers):
    """El acumulado de la última semana debe ser igual a la suma de todos los flujos netos."""
    semanas = (await client.get("/api/agents/cash-flow", headers=gerente_headers)).json()["semanas"]
    total_neto    = sum(s["flujo_neto"] for s in semanas)
    ultimo_acum   = semanas[-1]["acumulado"]
    assert abs(total_neto - ultimo_acum) < 1.0


@pytest.mark.asyncio
async def test_cash_flow_resumen_numerico(client, gerente_headers):
    r = (await client.get("/api/agents/cash-flow", headers=gerente_headers)).json()["resumen"]
    for campo in ("ingresos_proyectados", "gastos_estimados", "cobros_pendientes",
                  "cobrado_30d", "gastado_4s", "promedio_gastos_semanal"):
        assert isinstance(r[campo], (int, float))
        assert r[campo] >= 0


@pytest.mark.asyncio
async def test_cash_flow_formato_markdown(client, gerente_headers):
    resp = await client.get("/api/agents/cash-flow?formato=markdown", headers=gerente_headers)
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "Cash Flow" in resp.text
    assert "Proyección" in resp.text


@pytest.mark.asyncio
async def test_cash_flow_requiere_auth(client):
    resp = await client.get("/api/agents/cash-flow")
    assert resp.status_code == 403
