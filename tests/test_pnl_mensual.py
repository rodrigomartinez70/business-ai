"""
Tests del P&L comparativo (Estado de Resultados YTD, año actual vs año anterior).
"""

import pytest


@pytest.mark.asyncio
async def test_pnl_estructura(client, gerente_headers):
    resp = await client.get("/api/agents/pnl?fecha=2026-04-30", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "periodo" in data and "lineas" in data and "resumen" in data
    assert "actual" in data["periodo"] and "anterior" in data["periodo"]


@pytest.mark.asyncio
async def test_pnl_periodos_ytd(client, gerente_headers):
    p = (await client.get("/api/agents/pnl?fecha=2026-04-30", headers=gerente_headers)).json()["periodo"]
    assert p["actual"]["inicio"] == "2026-01-01"
    assert p["actual"]["fin"] == "2026-04-30"
    assert p["anterior"]["inicio"] == "2025-01-01"
    assert p["anterior"]["fin"] == "2025-04-30"


@pytest.mark.asyncio
async def test_pnl_lineas_y_variacion(client, gerente_headers):
    lineas = (await client.get("/api/agents/pnl?fecha=2026-04-30", headers=gerente_headers)).json()["lineas"]
    conceptos = [l["concepto"] for l in lineas]
    assert "= Ingresos Netos por Ventas" in conceptos
    assert "= Margen Bruto" in conceptos
    assert "= EBITDA" in conceptos
    assert "= Resultado Neto" in conceptos
    for l in lineas:
        assert l["var_abs"] == pytest.approx(l["actual"] - l["anterior"], abs=1.0)
        assert "tipo" in l


@pytest.mark.asyncio
async def test_pnl_resumen(client, gerente_headers):
    r = (await client.get("/api/agents/pnl?fecha=2026-04-30", headers=gerente_headers)).json()["resumen"]
    for k in ("ingresos_netos", "margen_bruto", "margen_bruto_pct", "ebitda", "resultado_neto"):
        assert k in r


@pytest.mark.asyncio
async def test_pnl_markdown(client, gerente_headers):
    resp = await client.get("/api/agents/pnl?fecha=2026-04-30&formato=markdown", headers=gerente_headers)
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "P&L comparativo" in resp.text


@pytest.mark.asyncio
async def test_pnl_requiere_auth(client):
    resp = await client.get("/api/agents/pnl")
    assert resp.status_code == 403
