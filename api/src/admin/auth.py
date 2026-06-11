"""
Auth del back-office MBI Admin — HTTP Basic contra ADMIN_USER/ADMIN_PASSWORD.

Es auth de PLATAFORMA (cross-tenant), separada de las API keys por-tenant. Si
ADMIN_PASSWORD no está seteada, el panel queda deshabilitado (503).
"""

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .. import config

_security = HTTPBasic(auto_error=False)


async def require_admin(cred: HTTPBasicCredentials = Depends(_security)) -> str:
    if not config.admin_disponible():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Back-office deshabilitado: definí ADMIN_PASSWORD en el entorno.")
    if cred is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida.",
            headers={"WWW-Authenticate": "Basic"})
    # Admin bootstrap del entorno (siempre disponible).
    if (config.ADMIN_PASSWORD
            and secrets.compare_digest(cred.username, config.ADMIN_USER)
            and secrets.compare_digest(cred.password, config.ADMIN_PASSWORD)):
        return cred.username
    # Usuarios gestionados en la DB.
    from .users import verificar
    if await verificar(cred.username, cred.password):
        return cred.username
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas.",
        headers={"WWW-Authenticate": "Basic"})
