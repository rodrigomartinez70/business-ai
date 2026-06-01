"""
Tests del agente de Control de Gastos.
"""

import pytest
from datetime import date, timedelta


FECHA_FIN    = date(2026, 4, 30)
FECHA_INICIO = date(2026, 4, 24)


@pytest.mark.asyncio
async def test_control_gastos_estructura_json(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/control-gastos?fecha_inicio={FECHA_INICIO}&fecha_fin={FECHA_FIN}",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "periodo" in data
    assert "resumen" in data
    assert "categorias" in data
    assert "alertas" in data
    assert "sin_categoria" in data
    assert "proveedores_nuevos" in data
    assert "top_gastos" in data


@pytest.mark.asyncio
async def test_control_gastos_periodo_correcto(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/control-gastos?fecha_inicio={FECHA_INICIO}&fecha_fin={FECHA_FIN}",
        headers=gerente_headers,
    )
    p = resp.json()["periodo"]
    assert p["inicio"] == str(FECHA_INICIO)
    assert p["fin"]    == str(FECHA_FIN)
    assert p["dias"]   == 7
    # período anterior debe ser los 7 días previos
    assert p["prev_fin"] == str(FECHA_INICIO - timedelta(days=1))


@pytest.mark.asyncio
async def test_control_gastos_resumen_numerico(client, gerente_headers):
    r = (await client.get(
        f"/api/agents/control-gastos?fecha_inicio={FECHA_INICIO}&fecha_fin={FECHA_FIN}",
        headers=gerente_headers,
    )).json()["resumen"]
    assert isinstance(r["total_actual"],   (int, float))
    assert isinstance(r["total_anterior"], (int, float))
    assert r["total_actual"]   >= 0
    assert r["total_anterior"] >= 0


@pytest.mark.asyncio
async def test_control_gastos_categorias_estructura(client, gerente_headers):
    cats = (await client.get(
        f"/api/agents/control-gastos?fecha_inicio={FECHA_INICIO}&fecha_fin={FECHA_FIN}",
        headers=gerente_headers,
    )).json()["categorias"]
    assert isinstance(cats, list)
    for c in cats:
        assert "categoria"      in c
        assert "monto_actual"   in c
        assert "monto_anterior" in c
        assert c["monto_actual"]   >= 0
        assert c["monto_anterior"] >= 0


@pytest.mark.asyncio
async def test_control_gastos_alertas_estructura(client, gerente_headers):
    alertas = (await client.get(
        f"/api/agents/control-gastos?fecha_inicio={FECHA_INICIO}&fecha_fin={FECHA_FIN}",
        headers=gerente_headers,
    )).json()["alertas"]
    for a in alertas:
        assert "categoria"    in a
        assert "variacion_pct"in a
        assert "nivel"        in a
        assert a["nivel"] in ("alerta", "critico")


@pytest.mark.asyncio
async def test_control_gastos_top_gastos_limite(client, gerente_headers):
    top = (await client.get(
        f"/api/agents/control-gastos?fecha_inicio={FECHA_INICIO}&fecha_fin={FECHA_FIN}",
        headers=gerente_headers,
    )).json()["top_gastos"]
    assert len(top) <= 5
    for g in top:
        assert "monto"     in g
        assert "categoria" in g
        assert g["monto"]  >= 0


@pytest.mark.asyncio
async def test_control_gastos_defaults(client, gerente_headers):
    """Sin parámetros usa los últimos 7 días."""
    resp = await client.get("/api/agents/control-gastos", headers=gerente_headers)
    assert resp.status_code == 200
    assert resp.json()["periodo"]["dias"] == 7


@pytest.mark.asyncio
async def test_control_gastos_formato_markdown(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/control-gastos?fecha_inicio={FECHA_INICIO}&fecha_fin={FECHA_FIN}&formato=markdown",
        headers=gerente_headers,
    )
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "Control de Gastos" in resp.text
    assert "categoría" in resp.text.lower()


@pytest.mark.asyncio
async def test_control_gastos_requiere_auth(client):
    resp = await client.get("/api/agents/control-gastos")
    assert resp.status_code == 403
