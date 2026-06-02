import pytest


@pytest.mark.asyncio
async def test_health_ok(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "conectada"


@pytest.mark.asyncio
async def test_models_endpoint(client, gerente_headers):
    resp = await client.get("/api/v1/models", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    ids = [m["id"] for m in data["data"]]
    # asistente-ia (text-to-SQL) + copiloto-tributario (conversacional)
    assert "copiloto-tributario" in ids
    assert len(data["data"]) == 2
