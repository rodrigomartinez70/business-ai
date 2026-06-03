"""
Tests del Agente Conciliación bancaria.
"""

import pytest
from datetime import date

from src.finanzas.conciliacion import _buscar


FECHA = date(2026, 1, 31)   # ventana que cubre la cartola de ejemplo del seed


# ── Algoritmo de match (unitario, sin DB) ───────────────────────────────

def test_buscar_match_por_monto_y_fecha():
    cands = [{"fecha": date(2026, 1, 14), "monto": 1120000.0, "used": False}]
    m = _buscar(1120000.0, date(2026, 1, 15), cands)   # 1 día de diferencia
    assert m is not None and m["used"] is True


def test_buscar_no_match_fuera_de_tolerancia():
    cands = [{"fecha": date(2026, 1, 1), "monto": 1000.0, "used": False}]
    assert _buscar(1000.0, date(2026, 1, 10), cands) is None      # >3 días
    assert _buscar(1500.0, date(2026, 1, 1), cands) is None       # monto distinto


def test_buscar_no_reutiliza_candidato():
    cands = [{"fecha": date(2026, 1, 6), "monto": 165000.0, "used": False}]
    assert _buscar(165000.0, date(2026, 1, 6), cands) is not None
    assert _buscar(165000.0, date(2026, 1, 6), cands) is None     # ya usado


# ── Endpoint ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_conciliacion_estructura(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/conciliacion?fecha={FECHA}&dias=31", headers=gerente_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "periodo" in data and "resumen" in data
    assert "tiene_cartola" in data and "sin_respaldo" in data


@pytest.mark.asyncio
async def test_conciliacion_con_cartola_del_seed(client, gerente_headers):
    data = (await client.get(
        f"/api/agents/conciliacion?fecha={FECHA}&dias=31", headers=gerente_headers)).json()
    r = data["resumen"]
    assert data["tiene_cartola"] is True
    assert r["movimientos"] == 3
    # dos abonos calzan con pagos existentes
    assert r["conciliados"] >= 2
    # el cargo de comisión no tiene respaldo
    assert data["sin_respaldo_total"] >= 1
    assert 0 <= r["pct_conciliado"] <= 100


@pytest.mark.asyncio
async def test_conciliacion_sin_cartola(client, gerente_headers):
    """Período sin movimientos → tiene_cartola False."""
    data = (await client.get(
        "/api/agents/conciliacion?fecha=2030-01-31&dias=30", headers=gerente_headers)).json()
    assert data["tiene_cartola"] is False
    assert data["resumen"]["movimientos"] == 0


@pytest.mark.asyncio
async def test_conciliacion_markdown(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/conciliacion?fecha={FECHA}&dias=31&formato=markdown",
        headers=gerente_headers)
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "Conciliación bancaria" in resp.text


@pytest.mark.asyncio
async def test_conciliacion_requiere_auth(client):
    resp = await client.get("/api/agents/conciliacion")
    assert resp.status_code == 403
