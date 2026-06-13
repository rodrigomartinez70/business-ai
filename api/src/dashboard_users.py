"""
Usuarios del dashboard web POR EMPRESA + sesión firmada (cookie).

Distinto de admin.users (back-office cross-tenant): acá cada empresa tiene sus
propios usuarios en public.dashboard_users. Reutiliza el hashing PBKDF2 del
back-office. La sesión es una cookie firmada con HMAC (stdlib, sin dependencias).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import time

from . import config
from .admin.users import hash_password, verify_password

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SESION_TTL = 60 * 60 * 12        # 12 horas


class DashUserError(Exception):
    """Error de validación (→ 400)."""


def _secret() -> bytes:
    return (config.DASHBOARD_SECRET or "mbi-dev-secret").encode()


# ── Sesión (cookie firmada) ──────────────────────────────────

def firmar_sesion(tenant_id: str, email: str) -> str:
    exp = int(time.time()) + _SESION_TTL
    payload = f"{tenant_id}|{email}|{exp}"
    b = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{b}.{sig}"


def verificar_sesion(token: str, tenant_id: str) -> str | None:
    """Devuelve el email si la cookie es válida para ese tenant y no expiró."""
    try:
        b, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()
        exp_sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, exp_sig):
            return None
        t_id, email, exp = payload.split("|")
        if t_id != tenant_id or int(exp) < int(time.time()):
            return None
        return email
    except Exception:                                 # noqa: BLE001
        return None


# ── Auth ─────────────────────────────────────────────────────

async def verificar(tenant_id: str, email: str, password: str) -> bool:
    if config.raw_pool is None:
        return False
    row = await config.raw_pool.fetchrow(
        "SELECT password_hash FROM public.dashboard_users "
        "WHERE tenant_id=$1 AND lower(email)=lower($2) AND activo=TRUE",
        tenant_id, email)
    return bool(row) and verify_password(password, row["password_hash"])


# ── CRUD (por empresa) ───────────────────────────────────────

async def listar(tenant_id: str) -> list[dict]:
    rows = await config.raw_pool.fetch(
        "SELECT id, email, activo, created_at FROM public.dashboard_users "
        "WHERE tenant_id=$1 ORDER BY email", tenant_id)
    return [dict(r) for r in rows]


async def crear(tenant_id: str, email: str, password: str) -> None:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise DashUserError("Email inválido.")
    if len(password or "") < 8:
        raise DashUserError("La contraseña debe tener al menos 8 caracteres.")
    existe = await config.raw_pool.fetchval(
        "SELECT 1 FROM public.dashboard_users WHERE tenant_id=$1 AND lower(email)=lower($2)",
        tenant_id, email)
    if existe:
        raise DashUserError(f"Ya existe el usuario '{email}' en esta empresa.")
    await config.raw_pool.execute(
        "INSERT INTO public.dashboard_users (tenant_id, email, password_hash) VALUES ($1,$2,$3)",
        tenant_id, email, hash_password(password))
    logger.info(f"[dashboard] usuario creado: {email} @ {tenant_id}")


async def cambiar_password(uid: int, password: str) -> None:
    if len(password or "") < 8:
        raise DashUserError("La contraseña debe tener al menos 8 caracteres.")
    await config.raw_pool.execute(
        "UPDATE public.dashboard_users SET password_hash=$2 WHERE id=$1",
        uid, hash_password(password))


async def set_activo(uid: int, activo: bool) -> None:
    await config.raw_pool.execute(
        "UPDATE public.dashboard_users SET activo=$2 WHERE id=$1", uid, activo)


async def eliminar(uid: int) -> None:
    await config.raw_pool.execute("DELETE FROM public.dashboard_users WHERE id=$1", uid)
