from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import tenant_registry
from .tenant import TenantContext, set_tenant

security = HTTPBearer()


def get_tenant_ctx(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> TenantContext:
    """
    Resuelve la API key → TenantContext y lo setea en el contextvar.
    El contextvar dura solo durante este request (asyncio copia el
    Context por coroutine — no hay leakage entre requests concurrentes).
    """
    ctx = tenant_registry.resolve_api_key(credentials.credentials)
    if ctx is None:
        raise HTTPException(status_code=401, detail="API key inválida.")
    set_tenant(ctx)
    return ctx


def get_role(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    Backward-compatible: retorna el rol como string.
    Internamente resuelve el tenant completo y setea el contextvar,
    por lo que todos los routers que usan `Depends(get_role)` ya
    tienen el TenantContext disponible vía get_tenant().
    """
    return get_tenant_ctx(credentials).rol
