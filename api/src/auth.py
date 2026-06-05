from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import tenant_registry
from .tenant import TenantContext, set_tenant

security = HTTPBearer()


async def get_tenant_ctx(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TenantContext:
    """
    Resuelve la API key → TenantContext y lo setea en el contextvar.
    Debe ser async para que set_tenant() modifique el contextvar del
    asyncio Task y sea visible al código async que se ejecuta después.
    (Las funciones sync corren en un thread pool; sus cambios a
    contextvars no se propagan de vuelta al Task de asyncio.)
    """
    ctx = tenant_registry.resolve_api_key(credentials.credentials)
    if ctx is None:
        raise HTTPException(status_code=401, detail="API key inválida.")
    set_tenant(ctx)
    return ctx


async def get_tenant_ctx_web(request: Request, key: str | None = None) -> TenantContext:
    """Auth flexible para vistas HTML abribles en el navegador: acepta la API key
    por query param `?key=...` o por header `Authorization: Bearer`. Resuelve el
    tenant y lo setea en el contextvar.

    Nota: pasar la key por URL queda en logs/historial del navegador; usar solo
    para dashboards de lectura."""
    api_key = key
    if not api_key:
        h = request.headers.get("Authorization", "")
        if h.startswith("Bearer "):
            api_key = h[len("Bearer "):].strip()
    ctx = tenant_registry.resolve_api_key(api_key) if api_key else None
    if ctx is None:
        raise HTTPException(status_code=401,
                            detail="API key inválida o ausente (usá ?key=... o Authorization: Bearer).")
    set_tenant(ctx)
    return ctx


async def get_role(ctx: TenantContext = Depends(get_tenant_ctx)) -> str:
    """
    Backward-compatible: retorna el rol como string.
    Depende de get_tenant_ctx, que ya setea el TenantContext en el
    contextvar antes de que el route handler corra.
    """
    return ctx.rol
