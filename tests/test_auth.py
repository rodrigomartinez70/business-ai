import pytest


@pytest.mark.asyncio
async def test_sin_token_retorna_403(client):
    """Sin header Authorization → 403 (HTTPBearer rechaza antes de llegar al handler)."""
    resp = await client.get("/api/agents/alertas")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_token_invalido_retorna_401(client):
    resp = await client.get(
        "/api/agents/alertas",
        headers={"Authorization": "Bearer token-que-no-existe"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_valido_da_acceso(client, gerente_headers):
    resp = await client.get("/api/agents/alertas", headers=gerente_headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_ingest_requiere_auth(client):
    resp = await client.post("/api/ingest/gastos")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ingest_tabla_no_permitida(client, gerente_headers):
    """audit_log no está en TABLAS_PERMITIDAS."""
    import io
    csv_content = b"descripcion,monto\ntest,100"
    resp = await client.post(
        "/api/ingest/audit_log?modo=validar",
        headers=gerente_headers,
        files={"archivo": ("test.csv", io.BytesIO(csv_content), "text/csv")},
    )
    assert resp.status_code == 400
    assert "no permitida" in resp.json()["detail"]
