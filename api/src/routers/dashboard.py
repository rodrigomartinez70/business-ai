"""
Dashboard web POR EMPRESA (público, con login) — servido en el subdominio del
tenant: {empresa-con-guiones}.majorbi.com (ej. test-mbi.majorbi.com → test_mbi).

El tenant se resuelve desde el header Host. El acceso es por usuario+contraseña
(public.dashboard_users), con sesión en cookie firmada (HMAC). Es distinto del
back-office /admin (Basic auth cross-tenant).
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .. import config, tenant_registry
from .. import dashboard_users as du
from ..finanzas.informe import calcular_informe
from ..finanzas.dashboard_web import renderizar_dashboard_web
from ..tenant import set_tenant, reset_tenant

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

_COOKIE = "mbi_dash"


def _tenant_de_hostname(host: str) -> str | None:
    """test-mbi.majorbi.com → 'test_mbi'. None si no es un subdominio de un nivel."""
    host = (host or "").split(":")[0].lower()
    base = config.DASHBOARD_BASE_DOMAIN.lower()
    if not host.endswith("." + base):
        return None
    sub = host[: -(len(base) + 1)]
    if not sub or "." in sub:                 # solo un nivel de subdominio
        return None
    return sub.replace("-", "_")


def _tenant_de_host(request: Request) -> str | None:
    return _tenant_de_hostname(request.headers.get("host") or "")


def _pagina_neutral() -> HTMLResponse:
    return HTMLResponse(
        '<div style="font-family:sans-serif;padding:60px;text-align:center;color:#475569">'
        '<h1 style="color:#1e3a8a">majorbi</h1>'
        '<p>Dashboard de empresa. Accedé desde el subdominio de tu empresa.</p></div>',
        status_code=404)


def _login_html(tenant_id: str, error: str = "") -> str:
    ctx = tenant_registry.get_tenant_by_id(tenant_id)
    biz = tenant_id
    if ctx is not None:
        token = set_tenant(ctx)
        try:
            biz = config.get_config().get("business", {}).get("name", tenant_id)
        finally:
            reset_tenant(token)
    err = f'<div class="err">{error}</div>' if error else ""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{biz} — Acceso</title>
<style>
 body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
   background:linear-gradient(120deg,#1e3a8a,#2563eb);min-height:100vh;display:flex;
   align-items:center;justify-content:center}}
 .box{{background:#fff;border-radius:16px;padding:34px 30px;width:330px;
   box-shadow:0 10px 40px rgba(0,0,0,.25)}}
 h1{{margin:0 0 4px;font-size:20px;color:#0f172a}} .sub{{color:#64748b;font-size:13px;margin:0 0 20px}}
 label{{font-size:12px;color:#475569;display:block;margin:12px 0 4px}}
 input{{width:100%;padding:10px 12px;border:1px solid #cbd5e1;border-radius:9px;font-size:14px;box-sizing:border-box}}
 button{{width:100%;margin-top:18px;padding:11px;border:0;border-radius:9px;background:#2563eb;
   color:#fff;font-size:15px;font-weight:600;cursor:pointer}}
 button:hover{{background:#1d4ed8}}
 .err{{background:#fee2e2;color:#991b1b;font-size:13px;padding:8px 10px;border-radius:8px;margin-bottom:8px}}
</style></head><body>
 <form class="box" method="post" action="/login">
   <h1>{biz}</h1><p class="sub">Ingresá para ver tu dashboard</p>
   {err}
   <label>Email</label><input type="email" name="email" autofocus required>
   <label>Contraseña</label><input type="password" name="password" required>
   <button type="submit">Entrar</button>
 </form></body></html>"""


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    tenant_id = _tenant_de_host(request)
    if tenant_id is None:
        return _pagina_neutral()
    ctx = tenant_registry.get_tenant_by_id(tenant_id)
    if ctx is None:
        return _pagina_neutral()
    email = du.verificar_sesion(request.cookies.get(_COOKIE, ""), tenant_id)
    if not email:
        return RedirectResponse("/login", status_code=303)
    token = set_tenant(ctx)
    try:
        data = await calcular_informe(date.today())
        cfg = config.get_config()
        biz = cfg.get("business", {}).get("name", tenant_id)
        html = renderizar_dashboard_web(data, cfg, biz, logout_url="/logout")
    finally:
        reset_tenant(token)
    return HTMLResponse(html)


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    tenant_id = _tenant_de_host(request)
    if tenant_id is None or tenant_registry.get_tenant_by_id(tenant_id) is None:
        return _pagina_neutral()
    return HTMLResponse(_login_html(tenant_id))


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    tenant_id = _tenant_de_host(request)
    if tenant_id is None or tenant_registry.get_tenant_by_id(tenant_id) is None:
        return _pagina_neutral()
    if not await du.verificar(tenant_id, email, password):
        return HTMLResponse(_login_html(tenant_id, "Email o contraseña incorrectos."),
                            status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(_COOKIE, du.firmar_sesion(tenant_id, email), max_age=du._SESION_TTL,
                    httponly=True, secure=True, samesite="lax")
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(_COOKIE)
    return resp


@router.get("/internal/caddy-ask")
async def caddy_ask(domain: str = ""):
    """Endpoint para el TLS on-demand de Caddy: 200 si el host corresponde a una
    empresa activa (Caddy emite el certificado), 404 si no (no lo emite). Permite
    *.majorbi.com → un certificado por empresa, sin config por tenant."""
    tid = _tenant_de_hostname(domain)
    if tid and tenant_registry.get_tenant_by_id(tid) is not None:
        return Response(status_code=200)
    return Response(status_code=404)
