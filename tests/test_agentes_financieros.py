"""
Tests de los agentes financieros quick-win: Cuentas por Pagar/Cobrar,
Presupuesto, Tesorería y CFO Virtual. Tenant de test = hotel.
"""

import pytest
from datetime import date

from src.finanzas.cuentas_por_pagar import _monto
from src.finanzas.presupuesto import _var

FECHA = date(2026, 4, 30)   # YTD cubre el rango del seed (ene–abr 2026)


# ── Unitarios sin DB ────────────────────────────────────────────────────

def test_cxp_monto_usa_total_y_fallback():
    assert _monto({"monto_total": 1190.0, "monto_neto": 1000.0, "monto_iva": 190.0}) == 1190.0
    # sin total → neto + iva
    assert _monto({"monto_total": None, "monto_neto": 1000.0, "monto_iva": 190.0}) == 1190.0
    assert _monto({"monto_total": 0, "monto_neto": 1000.0, "monto_iva": None}) == 1000.0


def test_presupuesto_var_pct():
    assert _var(110.0, 100.0) == 10.0
    assert _var(80.0, 100.0) == -20.0
    assert _var(50.0, 0) is None        # sin presupuesto → sin variación


# ── Cuentas por Pagar ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cxp_estructura(client, gerente_headers):
    data = (await client.get(
        f"/api/agents/cuentas-por-pagar?fecha={FECHA}", headers=gerente_headers)).json()
    assert {"total_por_pagar", "aging", "vencidas", "por_proveedor"} <= data.keys()
    assert {"por_vencer", "d1_30", "d31_60", "d60_mas"} <= data["aging"].keys()


@pytest.mark.asyncio
async def test_cxp_markdown(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/cuentas-por-pagar?fecha={FECHA}&formato=markdown", headers=gerente_headers)
    assert resp.status_code == 200
    assert "Cuentas por Pagar" in resp.text


# ── Cuentas por Cobrar ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cxc_estructura(client, gerente_headers):
    data = (await client.get(
        f"/api/agents/cuentas-por-cobrar?fecha={FECHA}", headers=gerente_headers)).json()
    assert {"total_por_cobrar", "dso", "aging", "detalle"} <= data.keys()
    assert data["vertical"] in ("hotel", "restaurante")


# ── Presupuesto ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_presupuesto_con_datos_del_seed(client, gerente_headers):
    data = (await client.get(
        f"/api/agents/presupuesto?fecha={FECHA}", headers=gerente_headers)).json()
    assert data["tiene_presupuesto"] is True
    assert data["ingresos"]["presupuesto"] > 0
    assert any(l["categoria"] == "ingresos" for l in data["lineas"])


@pytest.mark.asyncio
async def test_presupuesto_sin_datos(client, gerente_headers):
    data = (await client.get(
        "/api/agents/presupuesto?fecha=2099-04-30", headers=gerente_headers)).json()
    assert data["tiene_presupuesto"] is False


# ── Tesorería ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tesoreria_estructura(client, gerente_headers):
    data = (await client.get(
        f"/api/agents/tesoreria?fecha={FECHA}", headers=gerente_headers)).json()
    assert data["semaforo"] in ("ok", "alerta", "critico")
    assert len(data["proyeccion"]) == 8
    assert {"caja_estimada", "flujo_semanal", "propuesta_pagos"} <= data.keys()


# ── CFO Virtual ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cfo_consolida(client, gerente_headers):
    data = (await client.get(
        f"/api/agents/cfo?fecha={FECHA}", headers=gerente_headers)).json()
    assert data["semaforo"] in ("ok", "alerta", "critico")
    assert "puntos_clave" in data and "indicadores" in data
    assert {"rentabilidad", "liquidez", "por_cobrar", "por_pagar"} <= data["indicadores"].keys()


@pytest.mark.asyncio
async def test_cfo_markdown(client, gerente_headers):
    resp = await client.get(
        f"/api/agents/cfo?fecha={FECHA}&formato=markdown", headers=gerente_headers)
    assert resp.status_code == 200
    assert "CFO Virtual" in resp.text


# ── Auth ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agentes_financieros_requieren_auth(client):
    for ruta in ("cuentas-por-pagar", "cuentas-por-cobrar", "presupuesto", "tesoreria", "cfo"):
        assert (await client.get(f"/api/agents/{ruta}")).status_code == 403
