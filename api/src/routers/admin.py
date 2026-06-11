"""
Back-office MBI Admin — panel server-rendered (Jinja + HTMX) + API JSON.

Rutas (todas detrás de HTTP Basic, rol plataforma):
  GET  /admin                       → panel HTML (listado + alta de empresas)
  POST /admin/tenants               → alta (form) → devuelve banner + tabla (HTMX)
  POST /admin/tenants/{id}/toggle   → activar/desactivar → devuelve la tabla (HTMX)
  GET  /api/admin/tenants           → listado JSON
"""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..admin import schedules as sched
from ..admin import tenants as svc
from ..admin.auth import require_admin

router = APIRouter(tags=["admin"])

_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "admin" / "templates"))


@router.get("/admin", response_class=HTMLResponse)
async def panel(request: Request, _admin: str = Depends(require_admin)):
    return _TEMPLATES.TemplateResponse(
        "index.html",
        {"request": request, "tenants": await svc.listar(), "verticales": svc.VERTICALES})


@router.post("/admin/tenants", response_class=HTMLResponse)
async def alta(
    request: Request,
    tenant_id: str = Form(...),
    nombre:    str = Form(...),
    vertical:  str = Form(...),
    email_to:  str = Form(""),
    _admin:    str = Depends(require_admin),
):
    correos = [e.strip() for e in email_to.replace(";", ",").split(",") if e.strip()]
    error = creada = None
    try:
        creada = await svc.crear(tenant_id=tenant_id, nombre=nombre,
                                 vertical=vertical, email_to=correos)
    except svc.AdminError as e:
        error = str(e)
    return _TEMPLATES.TemplateResponse(
        "_resultado.html",
        {"request": request, "creada": creada, "error": error,
         "tenants": await svc.listar()})


@router.post("/admin/tenants/{tenant_id}/toggle", response_class=HTMLResponse)
async def toggle(
    request: Request,
    tenant_id: str,
    activo:    str = Form(...),
    _admin:    str = Depends(require_admin),
):
    try:
        await svc.set_activo(tenant_id, activo == "true")
    except svc.AdminError:
        pass
    return _TEMPLATES.TemplateResponse(
        "_tabla.html", {"request": request, "tenants": await svc.listar()})


@router.get("/api/admin/tenants")
async def api_listar(_admin: str = Depends(require_admin)):
    return JSONResponse(
        [{**t, "created_at": str(t.get("created_at"))} for t in await svc.listar()])


# ─────────────────────────────────────────────────────────────
# Programación de correos
# ─────────────────────────────────────────────────────────────

async def _tabla_sched(request: Request):
    return _TEMPLATES.TemplateResponse(
        "_sched_tabla.html",
        {"request": request, "schedules": await sched.listar(), "dias": sched.DIAS})


@router.get("/admin/schedules", response_class=HTMLResponse)
async def panel_schedules(request: Request, _admin: str = Depends(require_admin)):
    return _TEMPLATES.TemplateResponse(
        "schedules.html",
        {"request": request, "schedules": await sched.listar(),
         "tenants": await svc.listar(), "dias": sched.DIAS, "reportes": sched.REPORTES})


@router.post("/admin/schedules", response_class=HTMLResponse)
async def alta_schedule(
    request: Request,
    tenant_id:     str = Form(...),
    reporte:       str = Form("informe_financiero"),
    dia_semana:    int = Form(...),
    hora:          int = Form(...),
    minuto:        int = Form(0),
    destinatarios: str = Form(""),
    _admin:        str = Depends(require_admin),
):
    error = resultado = None
    try:
        await sched.crear(tenant_id=tenant_id, reporte=reporte, dia_semana=dia_semana,
                          hora=hora, minuto=minuto, destinatarios=destinatarios)
        resultado = "Programación creada."
    except sched.AdminError as e:
        error = str(e)
    return _TEMPLATES.TemplateResponse(
        "_sched_resultado.html",
        {"request": request, "schedules": await sched.listar(), "dias": sched.DIAS,
         "resultado": resultado, "error": error})


@router.post("/admin/schedules/{sid}/toggle", response_class=HTMLResponse)
async def toggle_schedule(request: Request, sid: int, activo: str = Form(...),
                          _admin: str = Depends(require_admin)):
    await sched.set_activo(sid, activo == "true")
    return await _tabla_sched(request)


@router.post("/admin/schedules/{sid}/delete", response_class=HTMLResponse)
async def borrar_schedule(request: Request, sid: int, _admin: str = Depends(require_admin)):
    await sched.eliminar(sid)
    return await _tabla_sched(request)


@router.get("/api/admin/schedules")
async def api_schedules(_admin: str = Depends(require_admin)):
    return JSONResponse([{**s, "created_at": str(s.get("created_at")),
                          "last_run": str(s.get("last_run"))} for s in await sched.listar()])


@router.post("/api/admin/schedules/tick")
async def schedules_tick(_admin: str = Depends(require_admin)):
    """Lo golpea el cron lector cada ~15 min. Envía los reportes vencidos."""
    return JSONResponse(await sched.ejecutar_pendientes())
