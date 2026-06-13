"""
Tests del dashboard genérico (P3) y el routing del dispatch.

El dashboard genérico es horizontal: para empresas sin POS, el dispatch debe
devolverlo en vez de crashear buscando un vertical inexistente.
"""

import pytest

from src.finanzas import dashboard_generico as dg
from src.verticals import dispatch, registry
from src.tenant import TenantContext, set_tenant, clear_tenant


def _ctx(vertical):
    return TenantContext(tenant_id="x", rol="", vertical=vertical, config={}, schema_cache={})


def test_dispatch_generico_para_vertical_sin_pos():
    set_tenant(_ctx("comercial"))
    try:
        assert dispatch.dashboard() is dg
    finally:
        clear_tenant()


def test_dispatch_pos_usa_su_dashboard():
    set_tenant(_ctx("restaurante"))
    try:
        assert dispatch.dashboard() is registry.cargar("restaurante").dashboard
    finally:
        clear_tenant()


def test_secciones_generico_claves():
    data = {
        "pnl": {"lineas": [], "resumen": {}},
        "gastos": {"resumen": {}, "categorias": [], "alertas": []},
        "conciliacion": {},
        "comercial_html": None,
        "ipc": None,
    }
    secs = dg.secciones_html(data, {})
    assert set(secs) == {"pnl", "comercial", "gastos", "conciliacion", "marketing", "tributario", "cierre", "ipc"}
    assert secs["cierre"] == ""        # sin datos de cierre → vacía
    assert secs["pnl"] == ""           # sin líneas de P&L → sección vacía
    assert secs["comercial"] == ""     # sin config de ventas → vacía
    assert secs["marketing"] == ""     # sin datos de marketing → vacía
    assert secs["tributario"] == ""    # sin datos tributarios → vacía


@pytest.mark.asyncio
async def test_fetch_opt_tabla_inexistente():
    """Las consultas a tablas opcionales (pagos sin POS) degradan a default/[]."""
    import asyncpg
    from src.agents._common import fetchval_opt, fetch_opt

    class _Conn:
        async def fetchval(self, *a):
            raise asyncpg.UndefinedTableError("relation does not exist")

        async def fetch(self, *a):
            raise asyncpg.UndefinedTableError("relation does not exist")

    c = _Conn()
    assert await fetchval_opt(c, "SELECT 1 FROM pagos", default=0) == 0
    assert await fetch_opt(c, "SELECT 1 FROM pagos") == []


def test_sec_pnl_con_lineas_se_renderiza():
    pnl = {"lineas": [{"concepto": "Ingresos", "tipo": "detalle", "actual": 100.0,
                       "anterior": 0.0, "var_abs": 100.0, "var_pct": None}],
           "resumen": {}, "periodo": {"actual": {"label": "2026 YTD"}, "anterior": {"label": "2025 YTD"}}}
    html = dg._sec_pnl(pnl, {})
    assert "P&L" in html
