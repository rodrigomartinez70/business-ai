"""
Usuarios del back-office MBI Admin (login con usuario + contraseña).

Se guardan en public.admin_users con la contraseña hasheada (PBKDF2-HMAC-SHA256 +
salt, stdlib — sin dependencias nuevas). Conviven con el admin bootstrap del
entorno (ADMIN_USER/ADMIN_PASSWORD), que siempre funciona para no quedar afuera.
"""

import hashlib
import hmac
import logging
import os
import re

from .. import config

logger = logging.getLogger(__name__)

_ITER = 200_000
_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{3,60}$")


class AdminError(Exception):
    """Error de validación de usuario (→ 400)."""


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:                                # noqa: BLE001
        return False


async def verificar(username: str, password: str) -> bool:
    """True si el usuario existe, está activo y la contraseña coincide."""
    if config.raw_pool is None:
        return False
    row = await config.raw_pool.fetchrow(
        "SELECT password_hash FROM public.admin_users WHERE username=$1 AND activo=TRUE",
        username)
    return bool(row) and verify_password(password, row["password_hash"])


# ─────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────

async def listar() -> list[dict]:
    rows = await config.raw_pool.fetch(
        "SELECT id, username, activo, created_at FROM public.admin_users ORDER BY username")
    return [dict(r) for r in rows]


async def crear(username: str, password: str) -> None:
    username = (username or "").strip()
    if not _USER_RE.match(username):
        raise AdminError("Usuario inválido (3-60 chars: letras, números, . _ @ -).")
    if len(password or "") < 8:
        raise AdminError("La contraseña debe tener al menos 8 caracteres.")
    existe = await config.raw_pool.fetchval(
        "SELECT 1 FROM public.admin_users WHERE username=$1", username)
    if existe:
        raise AdminError(f"Ya existe el usuario '{username}'.")
    await config.raw_pool.execute(
        "INSERT INTO public.admin_users (username, password_hash) VALUES ($1, $2)",
        username, hash_password(password))
    logger.info(f"[admin] usuario creado: {username}")


async def cambiar_password(uid: int, password: str) -> None:
    if len(password or "") < 8:
        raise AdminError("La contraseña debe tener al menos 8 caracteres.")
    await config.raw_pool.execute(
        "UPDATE public.admin_users SET password_hash=$2 WHERE id=$1",
        uid, hash_password(password))
    logger.info(f"[admin] password cambiada para usuario #{uid}")


async def set_activo(uid: int, activo: bool) -> None:
    await config.raw_pool.execute(
        "UPDATE public.admin_users SET activo=$2 WHERE id=$1", uid, activo)


async def eliminar(uid: int) -> None:
    await config.raw_pool.execute("DELETE FROM public.admin_users WHERE id=$1", uid)
