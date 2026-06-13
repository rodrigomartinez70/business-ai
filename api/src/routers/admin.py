"""
Back-office MBI Admin — panel server-rendered (Jinja + HTMX) + API JSON.

Rutas (todas detrás de HTTP Basic, rol plataforma):
  GET  /admin                       → panel HTML (listado + alta de empresas)
  POST /admin/tenants               → alta (form) → devuelve banner + tabla (HTMX)
  POST /admin/tenants/{id}/toggle   → activar/desactivar → devuelve la tabla (HTMX)
  GET  /api/admin/tenants           → listado JSON
"""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from .. import config, tenant_registry
from ..admin import config_editor as cfged
from ..admin import integraciones as integ
from ..admin import modelo as modelo_svc
from ..admin import schedules as sched
from ..admin import sii as sii_svc
from ..admin import tenants as svc
from ..admin import users as usr
from ..admin.auth import require_admin
from ..finanzas.informe import calcular_informe, renderizar_informe_html
from ..tenant import set_tenant, reset_tenant

router = APIRouter(tags=["admin"])

_TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "admin" / "templates"))


def _ctx_packs(preset_id: str) -> dict:
    """Contexto para el partial de checkboxes de packs (con los del preset marcados)."""
    presets = svc.presets_catalogo()
    sel = next((p for p in presets if p["id"] == preset_id), presets[0])
    return {"packs": svc.packs_catalogo(), "marcados": set(sel["packs"])}


@router.get("/admin", response_class=HTMLResponse)
async def panel(request: Request, _admin: str = Depends(require_admin)):
    presets = svc.presets_catalogo()
    return _TEMPLATES.TemplateResponse(
        "index.html",
        {"request": request, "tenants": await svc.listar(), "presets": presets,
         **_ctx_packs(presets[0]["id"])})


@router.get("/admin/packs-form", response_class=HTMLResponse)
async def packs_form(request: Request, preset: str = "",
                     _admin: str = Depends(require_admin)):
    """Refresca los checkboxes de packs al cambiar el preset (HTMX)."""
    return _TEMPLATES.TemplateResponse(
        "_packs_form.html", {"request": request, **_ctx_packs(preset)})


@router.post("/admin/tenants", response_class=HTMLResponse)
async def alta(
    request: Request,
    tenant_id: str = Form(...),
    nombre:    str = Form(...),
    preset:    str = Form(...),
    packs:     list[str] = Form(default=[]),
    email_to:  str = Form(""),
    _admin:    str = Depends(require_admin),
):
    correos = [e.strip() for e in email_to.replace(";", ",").split(",") if e.strip()]
    error = creada = None
    try:
        creada = await svc.crear(tenant_id=tenant_id, nombre=nombre,
                                 preset=preset, packs=packs, email_to=correos)
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


@router.get("/admin/db", response_class=HTMLResponse)
async def panel_db(request: Request, _admin: str = Depends(require_admin)):
    """Acceso a PostgreSQL embebido (Adminer) + link de respaldo."""
    return _TEMPLATES.TemplateResponse("db.html", {"request": request})


@router.get("/admin/tenants/{tenant_id}/modelo", response_class=HTMLResponse)
async def panel_modelo(request: Request, tenant_id: str, _admin: str = Depends(require_admin)):
    return _TEMPLATES.TemplateResponse(
        "modelo.html", {"request": request, **(await modelo_svc.modelo(tenant_id))})


@router.get("/admin/tenants/{tenant_id}/preview", response_class=HTMLResponse)
async def preview_email(tenant_id: str, _admin: str = Depends(require_admin)):
    """Previsualiza el email (Informe Financiero) de la empresa, tal cual se enviaría:
    módulos activos + datos/integraciones de ese tenant. Sin API key, solo admin."""
    ctx = tenant_registry.get_tenant_by_id(tenant_id)
    if ctx is None:
        return HTMLResponse(
            f'<div style="font-family:sans-serif;padding:40px;color:#991b1b;">'
            f'La empresa «{tenant_id}» no existe o está inactiva.</div>', status_code=404)
    token = set_tenant(ctx)
    try:
        data = await calcular_informe(date.today())
        cfg = config.get_config()
        biz = cfg.get("business", {}).get("name", tenant_id)
        html = renderizar_informe_html(data, cfg, biz)
    finally:
        reset_tenant(token)
    return HTMLResponse(html)


@router.get("/admin/tenants/{tenant_id}/modulos", response_class=HTMLResponse)
async def panel_modulos(request: Request, tenant_id: str, _admin: str = Depends(require_admin)):
    return _TEMPLATES.TemplateResponse(
        "modulos.html", {"request": request, **(await svc.modulos_de(tenant_id))})


@router.post("/admin/tenants/{tenant_id}/modulos/{clave}", response_class=HTMLResponse)
async def toggle_modulo(request: Request, tenant_id: str, clave: str,
                        activo: str = Form(...), _admin: str = Depends(require_admin)):
    try:
        await svc.set_modulo(tenant_id, clave, activo == "true")
    except svc.AdminError:
        pass
    return _TEMPLATES.TemplateResponse(
        "_modulos_lista.html", {"request": request, **(await svc.modulos_de(tenant_id))})


# ─────────────────────────────────────────────────────────────
# Editor de config (KPIs / particularidades) por tenant
# ─────────────────────────────────────────────────────────────

@router.get("/admin/tenants/{tenant_id}/config", response_class=HTMLResponse)
async def panel_config(request: Request, tenant_id: str, _admin: str = Depends(require_admin)):
    vertical = await cfged.vertical_de(tenant_id)
    return _TEMPLATES.TemplateResponse(
        "config_editor.html",
        {"request": request, "tenant_id": tenant_id,
         "config_yaml": await cfged.cargar_yaml(tenant_id),
         "metricas": cfged.catalogo_metricas(vertical)})


@router.post("/admin/tenants/{tenant_id}/config", response_class=HTMLResponse)
async def guardar_config(request: Request, tenant_id: str, contenido: str = Form(...),
                         _admin: str = Depends(require_admin)):
    try:
        errores = await cfged.guardar(tenant_id, contenido)
    except cfged.AdminError as e:
        errores = [str(e)]
    return _TEMPLATES.TemplateResponse(
        "_config_resultado.html", {"request": request, "errores": errores})


# ─────────────────────────────────────────────────────────────
# Integraciones por tenant
# ─────────────────────────────────────────────────────────────

@router.get("/admin/tenants/{tenant_id}/integraciones", response_class=HTMLResponse)
async def panel_integraciones(request: Request, tenant_id: str,
                              _admin: str = Depends(require_admin)):
    return _TEMPLATES.TemplateResponse(
        "integraciones.html",
        {"request": request, **(await integ.estado(tenant_id)),
         "sii_caps": (await sii_svc.estado(tenant_id))["sii_caps"],
         "sii_cert": await sii_svc.cert_estado(tenant_id)})


@router.post("/admin/tenants/{tenant_id}/sii/{cap}", response_class=HTMLResponse)
async def toggle_sii(request: Request, tenant_id: str, cap: str,
                     activo: str = Form(...), _admin: str = Depends(require_admin)):
    try:
        await sii_svc.set_cap(tenant_id, cap, activo == "true")
    except sii_svc.AdminError:
        pass
    return _TEMPLATES.TemplateResponse(
        "_sii_caps.html", {"request": request, **(await sii_svc.estado(tenant_id))})


@router.post("/admin/tenants/{tenant_id}/rcv", response_class=HTMLResponse)
async def subir_rcv(request: Request, tenant_id: str,
                    archivo: UploadFile = File(...), modo: str = Form("insertar"),
                    _admin: str = Depends(require_admin)):
    contenido = await archivo.read()
    res = msg = None
    try:
        res = await sii_svc.subir_rcv(tenant_id, contenido, modo)
    except (sii_svc.AdminError, ValueError) as e:
        msg = f"⚠ {e}"
    return _TEMPLATES.TemplateResponse(
        "_sii_resultado.html", {"request": request, "res": res, "msg": msg})


@router.post("/admin/tenants/{tenant_id}/sii-cert", response_class=HTMLResponse)
async def subir_cert_sii(request: Request, tenant_id: str,
                         archivo: UploadFile = File(...), password: str = Form(""),
                         rut: str = Form(""), ambiente: str = Form("certificacion"),
                         _admin: str = Depends(require_admin)):
    from ..integraciones.sii_auth import SiiAuthError
    contenido = await archivo.read()
    msg = None
    try:
        await sii_svc.guardar_cert(tenant_id, contenido, password, rut, ambiente)
        msg = "✓ Certificado válido y guardado."
    except (sii_svc.AdminError, SiiAuthError) as e:
        msg = f"⚠ {e}"
    return _TEMPLATES.TemplateResponse(
        "_sii_cert.html",
        {"request": request, "tenant_id": tenant_id,
         "sii_cert": await sii_svc.cert_estado(tenant_id), "cert_msg": msg})


@router.post("/admin/tenants/{tenant_id}/sii-cert/probar", response_class=HTMLResponse)
async def probar_cert_sii(request: Request, tenant_id: str,
                          _admin: str = Depends(require_admin)):
    from ..integraciones.sii_auth import SiiAuthError
    msg = None
    try:
        token = await sii_svc.probar_conexion(tenant_id)
        msg = f"✓ Conexión OK con el SII. Token: {token[:14]}…"
    except (sii_svc.AdminError, SiiAuthError) as e:
        msg = f"⚠ {e}"
    except Exception as e:                        # noqa: BLE001 — red/SOAP del SII
        msg = f"⚠ No se pudo conectar al SII: {e}"
    return _TEMPLATES.TemplateResponse(
        "_sii_cert.html",
        {"request": request, "tenant_id": tenant_id,
         "sii_cert": await sii_svc.cert_estado(tenant_id), "cert_msg": msg})


@router.post("/admin/tenants/{tenant_id}/integraciones/{proveedor}", response_class=HTMLResponse)
async def guardar_integracion(request: Request, tenant_id: str, proveedor: str,
                              _admin: str = Depends(require_admin)):
    form = await request.form()
    msg = None
    try:
        await integ.guardar(tenant_id, proveedor, dict(form))
        msg = f"Integración {proveedor} guardada."
    except integ.AdminError as e:
        msg = f"⚠ {e}"
    return _TEMPLATES.TemplateResponse(
        "_integraciones_cards.html",
        {"request": request, "mensaje": msg, **(await integ.estado(tenant_id))})


@router.post("/admin/tenants/{tenant_id}/integraciones/{proveedor}/desconectar",
             response_class=HTMLResponse)
async def desconectar_integracion(request: Request, tenant_id: str, proveedor: str,
                                  _admin: str = Depends(require_admin)):
    await integ.desconectar(tenant_id, proveedor)
    return _TEMPLATES.TemplateResponse(
        "_integraciones_cards.html",
        {"request": request, "mensaje": f"Integración {proveedor} desconectada (vuelve a mock).",
         **(await integ.estado(tenant_id))})


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


@router.get("/admin/schedules/tabla", response_class=HTMLResponse)
async def tabla_schedules(request: Request, _admin: str = Depends(require_admin)):
    return await _tabla_sched(request)


@router.get("/admin/schedules/{sid}/edit", response_class=HTMLResponse)
async def editar_form(request: Request, sid: int, _admin: str = Depends(require_admin)):
    return _TEMPLATES.TemplateResponse(
        "_sched_fila_edit.html",
        {"request": request, "s": await sched.obtener(sid), "dias": sched.DIAS})


@router.post("/admin/schedules/{sid}", response_class=HTMLResponse)
async def actualizar_schedule(
    request: Request, sid: int,
    dia_semana:    int = Form(...),
    hora:          int = Form(...),
    minuto:        int = Form(0),
    destinatarios: str = Form(""),
    _admin:        str = Depends(require_admin),
):
    try:
        await sched.actualizar(sid=sid, dia_semana=dia_semana, hora=hora,
                               minuto=minuto, destinatarios=destinatarios)
    except sched.AdminError:
        pass
    return await _tabla_sched(request)


# ─────────────────────────────────────────────────────────────
# Usuarios del back-office
# ─────────────────────────────────────────────────────────────

async def _tabla_usuarios(request: Request):
    return _TEMPLATES.TemplateResponse(
        "_usuarios_tabla.html", {"request": request, "usuarios": await usr.listar()})


@router.get("/admin/usuarios", response_class=HTMLResponse)
async def panel_usuarios(request: Request, _admin: str = Depends(require_admin)):
    return _TEMPLATES.TemplateResponse(
        "usuarios.html", {"request": request, "usuarios": await usr.listar()})


@router.post("/admin/usuarios", response_class=HTMLResponse)
async def alta_usuario(request: Request, username: str = Form(...), password: str = Form(...),
                       _admin: str = Depends(require_admin)):
    error = resultado = None
    try:
        await usr.crear(username, password)
        resultado = f"Usuario «{username}» creado."
    except usr.AdminError as e:
        error = str(e)
    return _TEMPLATES.TemplateResponse(
        "_usuarios_resultado.html",
        {"request": request, "usuarios": await usr.listar(), "resultado": resultado, "error": error})


@router.get("/admin/usuarios/tabla", response_class=HTMLResponse)
async def tabla_usuarios(request: Request, _admin: str = Depends(require_admin)):
    return await _tabla_usuarios(request)


@router.get("/admin/usuarios/{uid}/password", response_class=HTMLResponse)
async def form_password(request: Request, uid: int, _admin: str = Depends(require_admin)):
    u = next((x for x in await usr.listar() if x["id"] == uid), None)
    return _TEMPLATES.TemplateResponse("_usuario_fila_pass.html", {"request": request, "u": u})


@router.post("/admin/usuarios/{uid}/password", response_class=HTMLResponse)
async def cambiar_password(request: Request, uid: int, password: str = Form(...),
                          _admin: str = Depends(require_admin)):
    try:
        await usr.cambiar_password(uid, password)
    except usr.AdminError:
        pass
    return await _tabla_usuarios(request)


@router.post("/admin/usuarios/{uid}/toggle", response_class=HTMLResponse)
async def toggle_usuario(request: Request, uid: int, activo: str = Form(...),
                         _admin: str = Depends(require_admin)):
    await usr.set_activo(uid, activo == "true")
    return await _tabla_usuarios(request)


@router.post("/admin/usuarios/{uid}/delete", response_class=HTMLResponse)
async def borrar_usuario(request: Request, uid: int, _admin: str = Depends(require_admin)):
    await usr.eliminar(uid)
    return await _tabla_usuarios(request)


@router.get("/api/admin/schedules")
async def api_schedules(_admin: str = Depends(require_admin)):
    return JSONResponse([{**s, "created_at": str(s.get("created_at")),
                          "last_run": str(s.get("last_run"))} for s in await sched.listar()])


@router.post("/api/admin/schedules/tick")
async def schedules_tick(_admin: str = Depends(require_admin)):
    """Lo golpea el cron lector cada ~15 min. Envía los reportes vencidos."""
    return JSONResponse(await sched.ejecutar_pendientes())
