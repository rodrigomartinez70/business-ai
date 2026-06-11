"""
Tests del back-office MBI Admin (gestión de tenants).
En el entorno de test ADMIN_PASSWORD no está seteada → el panel está deshabilitado (503).
"""

import pytest

from src.admin import tenants as svc


# ── Validación de slug (unitario, sin DB) ───────────────────────────────

def test_slug_valido():
    assert svc._TENANT_RE.match("restaurante_xyz")
    assert svc._TENANT_RE.match("hotel2")


def test_slug_invalido():
    assert not svc._TENANT_RE.match("2hotel")        # empieza con número
    assert not svc._TENANT_RE.match("Hotel")         # mayúscula
    assert not svc._TENANT_RE.match("ab")            # muy corto
    assert not svc._TENANT_RE.match("con espacio")
    assert not svc._TENANT_RE.match('drop";--')      # caracteres peligrosos


# ── Construcción de config desde la plantilla del vertical ──────────────

def test_construir_config_override():
    cfg = svc._construir_config("Restaurante XYZ", "restaurante",
                                ["a@x.cl", "b@x.cl"])
    assert cfg["business"]["name"] == "Restaurante XYZ"
    assert cfg["business"]["vertical"] == "restaurante"
    assert cfg["report"]["email_to"] == ["a@x.cl", "b@x.cl"]


def test_construir_config_vertical_invalido():
    with pytest.raises(svc.AdminError):
        svc._construir_config("X", "inexistente", [])


# ── Módulos del informe ─────────────────────────────────────────────────

def test_modulo_activo_default_on():
    from src.finanzas.informe import modulo_activo, MODULOS
    assert len(MODULOS) == 10
    assert modulo_activo({}, "marketing") is True                       # ausente = on
    assert modulo_activo({"report": {"modulos": {"marketing": False}}}, "marketing") is False
    assert modulo_activo({"report": {"modulos": {"marketing": False}}}, "gastos") is True


@pytest.mark.asyncio
async def test_set_modulo_desconocido():
    with pytest.raises(svc.AdminError):
        await svc.set_modulo("x", "modulo_inexistente", False)


# ── Integraciones por tenant ────────────────────────────────────────────

def test_proveedores_integraciones():
    from src.admin import integraciones as integ
    assert {"meta", "toteat", "odoo", "defontana"} <= set(integ.PROVEEDORES)
    # cada proveedor tiene un campo access_token secreto + cuenta_id
    for prov, meta in integ.PROVEEDORES.items():
        cols = {c for c, _l, _s in meta["campos"]}
        assert "access_token" in cols and "cuenta_id" in cols, prov
        secretos = {c for c, _l, s in meta["campos"] if s}
        assert secretos == {"access_token"}, prov


@pytest.mark.asyncio
async def test_guardar_integracion_proveedor_invalido():
    from src.admin import integraciones as integ
    with pytest.raises(integ.AdminError):
        await integ.guardar("x", "proveedor_inexistente", {})


# ── Panel deshabilitado sin ADMIN_PASSWORD ──────────────────────────────

@pytest.mark.asyncio
async def test_panel_deshabilitado_sin_password(client):
    # Sin credenciales Basic y sin ADMIN_PASSWORD → 503 (deshabilitado).
    resp = await client.get("/admin")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_api_admin_tenants_deshabilitado(client):
    resp = await client.get("/api/admin/tenants")
    assert resp.status_code == 503
