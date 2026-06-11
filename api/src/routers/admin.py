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
