"""
Tests del scheduler de reportes (MBI Admin). ADMIN_PASSWORD no seteada en test → 503.
"""

import pytest

from src.admin import schedules as sched


def test_parse_dest():
    assert sched._parse_dest("a@x.cl, b@x.cl; c@x.cl") == ["a@x.cl", "b@x.cl", "c@x.cl"]
    assert sched._parse_dest("") == []
    assert sched._parse_dest(None) == []


def test_dias_y_reportes():
    assert sched.DIAS[1] == "Lunes" and sched.DIAS[7] == "Domingo"
    assert "informe_financiero" in sched.REPORTES


@pytest.mark.asyncio
async def test_crear_valida_antes_de_db():
    # reporte inválido → AdminError antes de tocar la DB
    with pytest.raises(sched.AdminError):
        await sched.crear(tenant_id="x", reporte="nope", dia_semana=1,
                          hora=9, minuto=0, destinatarios=None)
    # día inválido
    with pytest.raises(sched.AdminError):
        await sched.crear(tenant_id="x", reporte="informe_financiero", dia_semana=9,
                          hora=9, minuto=0, destinatarios=None)
    # hora inválida
    with pytest.raises(sched.AdminError):
        await sched.crear(tenant_id="x", reporte="informe_financiero", dia_semana=1,
                          hora=25, minuto=0, destinatarios=None)


@pytest.mark.asyncio
async def test_actualizar_valida():
    with pytest.raises(sched.AdminError):
        await sched.actualizar(sid=1, dia_semana=0, hora=9, minuto=0, destinatarios=None)
    with pytest.raises(sched.AdminError):
        await sched.actualizar(sid=1, dia_semana=1, hora=24, minuto=0, destinatarios=None)


@pytest.mark.asyncio
async def test_tick_requiere_admin(client):
    resp = await client.post("/api/admin/schedules/tick")
    assert resp.status_code == 503        # panel deshabilitado sin ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_panel_schedules_deshabilitado(client):
    resp = await client.get("/admin/schedules")
    assert resp.status_code == 503
