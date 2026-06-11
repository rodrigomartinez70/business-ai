"""
Servicio de ciclo de vida de tenants (back-office MBI Admin).

Provisiona y administra empresas a nivel de plataforma:
  - crea el schema Postgres del tenant + aplica el schema.sql del vertical,
  - guarda la configuración como JSONB en public.tenants.config (editable por la UI),
  - genera y registra la API key (rol gerente),
  - activa/desactiva (reversible, sin borrar datos).

Usa config.raw_pool (sin scope de tenant). Tras cada cambio recarga el registry en
memoria para que el nuevo tenant/key funcione sin reiniciar la API.
"""

import hashlib
import json
import logging
import re
import secrets
from pathlib import Path

import yaml

from .. import config, tenant_registry

logger = logging.getLogger(__name__)

_SRC_DIR = Path(__file__).resolve().parents[1]          # .../api/src
VERTICALES = ("hotel", "restaurante")
_TENANT_RE = re.compile(r"^[a-z][a-z0-9_]{2,59}$")       # slug seguro para nombre de schema


class AdminError(Exception):
    """Error de validación/operación de administración (se traduce a 400)."""


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _schema_sql(vertical: str) -> Path:
    return _SRC_DIR / "verticals" / vertical / "schema.sql"


def _config_template(vertical: str) -> dict:
    p = _SRC_DIR / "verticals" / vertical / "config.template.yaml"
    if not p.exists():
        raise AdminError(f"No existe la plantilla de config del vertical '{vertical}'.")
    with open(p) as f:
        return yaml.safe_load(f) or {}


def _construir_config(nombre: str, vertical: str, email_to: list[str]) -> dict:
    cfg = _config_template(vertical)
    cfg.setdefault("business", {})
    cfg["business"]["name"] = nombre
    cfg["business"]["vertical"] = vertical
    if email_to:
        cfg.setdefault("report", {})
        cfg["report"]["email_to"] = email_to
    return cfg


async def _recargar_registry() -> None:
    await tenant_registry.load_all_tenants(
        pool             = config.raw_pool,
        legacy_api_keys  = config.API_KEYS,
        legacy_config    = config.CONFIG,
        legacy_tenant_id = "hotel_mbi",
    )


# ─────────────────────────────────────────────────────────────
# Lectura
# ─────────────────────────────────────────────────────────────

async def listar() -> list[dict]:
    from ..finanzas.informe import MODULOS
    rows = await config.raw_pool.fetch(
        """SELECT t.id, t.nombre, t.vertical, t.activo, t.created_at, t.config,
                  (t.config IS NOT NULL) AS config_en_db,
                  (SELECT COUNT(*) FROM public.api_keys k
                    WHERE k.tenant_id = t.id AND k.activa) AS keys_activas
             FROM public.tenants t
            ORDER BY t.created_at DESC, t.id""")
    total = len(MODULOS)
    out = []
    for r in rows:
        d = dict(r)
        cfg = d.pop("config")
        if cfg is not None and not isinstance(cfg, dict):
            cfg = json.loads(cfg)
        mods = ((cfg or {}).get("report") or {}).get("modulos") or {}
        # Sin config de módulos = todos activos (clave ausente = on).
        d["modulos_activos"] = sum(1 for c, _a, _t in MODULOS if mods.get(c, True))
        d["modulos_total"] = total
        out.append(d)
    return out


# ─────────────────────────────────────────────────────────────
# Alta
# ─────────────────────────────────────────────────────────────

async def crear(*, tenant_id: str, nombre: str, vertical: str,
                email_to: list[str] | None = None) -> dict:
    tenant_id = (tenant_id or "").strip().lower()
    nombre    = (nombre or "").strip()
    vertical  = (vertical or "").strip().lower()
    email_to  = email_to or []

    if not _TENANT_RE.match(tenant_id):
        raise AdminError("ID inválido: minúsculas, empieza con letra, 3-60 chars [a-z0-9_].")
    if vertical not in VERTICALES:
        raise AdminError(f"Vertical inválido. Opciones: {', '.join(VERTICALES)}.")
    if not nombre:
        raise AdminError("El nombre de la empresa es obligatorio.")
    if not _schema_sql(vertical).exists():
        raise AdminError(f"No existe schema.sql del vertical '{vertical}'.")

    existe = await config.raw_pool.fetchval(
        "SELECT 1 FROM public.tenants WHERE id = $1", tenant_id)
    if existe:
        raise AdminError(f"Ya existe una empresa con id '{tenant_id}'.")

    cfg = _construir_config(nombre, vertical, email_to)
    schema_ddl = _schema_sql(vertical).read_text()
    api_key = f"{tenant_id[:10]}_{secrets.token_hex(12)}"

    async with config.raw_pool.acquire() as conn:
        # No envolvemos CREATE SCHEMA en una transacción con el resto para que el
        # search_path del DDL no afecte a los INSERT de control (public.*).
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"')
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}"')
            await conn.execute(schema_ddl)
        await _otorgar_permisos(conn, tenant_id)

        await conn.execute(
            """INSERT INTO public.tenants (id, nombre, vertical, config_path, config, activo)
               VALUES ($1, $2, $3, $4, $5::jsonb, TRUE)""",
            tenant_id, nombre, vertical, f"/app/tenants/{tenant_id}/config.yaml",
            json.dumps(cfg))
        await conn.execute(
            """INSERT INTO public.api_keys (key_hash, tenant_id, rol, descripcion, activa)
               VALUES ($1, $2, 'gerente', $3, TRUE)""",
            hash_key(api_key), tenant_id, f"gerente — {tenant_id}")

    await _recargar_registry()
    logger.info(f"[admin] tenant creado: {tenant_id} ({vertical})")
    # La API key se devuelve UNA sola vez (solo se guarda su hash).
    return {"tenant_id": tenant_id, "vertical": vertical, "api_key": api_key}


async def _otorgar_permisos(conn, tenant_id: str) -> None:
    """Otorga permisos a los roles de lectura/ingest si existen (en prod el
    superusuario ya tiene acceso, así que esto es no-op)."""
    perms = [
        f'GRANT USAGE ON SCHEMA "{tenant_id}" TO negocio_user',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA "{tenant_id}" TO negocio_user',
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{tenant_id}" TO negocio_user',
        f'GRANT USAGE ON SCHEMA "{tenant_id}" TO negocio_ingest',
        f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA "{tenant_id}" TO negocio_ingest',
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{tenant_id}" TO negocio_ingest',
    ]
    import asyncpg
    for stmt in perms:
        try:
            await conn.execute(stmt)
        except asyncpg.UndefinedObjectError:
            pass


# ─────────────────────────────────────────────────────────────
# Activar / desactivar (reversible — no borra datos)
# ─────────────────────────────────────────────────────────────

async def _cargar_config_efectivo(tenant_id: str) -> dict:
    """Config vigente del tenant: JSONB de la DB si existe, si no el YAML del config_path."""
    row = await config.raw_pool.fetchrow(
        "SELECT config, config_path FROM public.tenants WHERE id = $1", tenant_id)
    if not row:
        raise AdminError(f"No existe la empresa '{tenant_id}'.")
    if row["config"] is not None:
        cfg = row["config"]
        return cfg if isinstance(cfg, dict) else json.loads(cfg)
    try:
        with open(row["config_path"]) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:                            # noqa: BLE001
        raise AdminError(f"No se pudo leer el config del tenant: {e}")


async def modulos_de(tenant_id: str) -> dict:
    """Estado de los módulos del informe para un tenant (para la UI de toggles)."""
    from ..finanzas.informe import MODULOS, modulo_activo
    cfg = await _cargar_config_efectivo(tenant_id)
    return {
        "tenant_id": tenant_id,
        "nombre": cfg.get("business", {}).get("name", tenant_id),
        "modulos": [{"clave": c, "titulo": t, "activo": modulo_activo(cfg, c)}
                    for c, _anchor, t in MODULOS],
    }


async def set_modulo(tenant_id: str, clave: str, activo: bool) -> None:
    """Activa/desactiva un módulo del informe. Escribe el config completo a JSONB
    (promueve el tenant a config-en-DB, preservando todo) y recarga el registry."""
    from ..finanzas.informe import MODULOS
    if clave not in {c for c, _a, _t in MODULOS}:
        raise AdminError(f"Módulo desconocido: {clave}.")
    cfg = await _cargar_config_efectivo(tenant_id)
    cfg.setdefault("report", {})
    cfg["report"].setdefault("modulos", {})
    cfg["report"]["modulos"][clave] = activo
    await config.raw_pool.execute(
        "UPDATE public.tenants SET config = $2::jsonb WHERE id = $1",
        tenant_id, json.dumps(cfg))
    await _recargar_registry()
    logger.info(f"[admin] {tenant_id} módulo {clave} → {'on' if activo else 'off'}")


async def set_activo(tenant_id: str, activo: bool) -> dict:
    row = await config.raw_pool.fetchrow(
        "SELECT id FROM public.tenants WHERE id = $1", tenant_id)
    if not row:
        raise AdminError(f"No existe la empresa '{tenant_id}'.")
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE public.tenants SET activo = $2 WHERE id = $1", tenant_id, activo)
            await conn.execute(
                "UPDATE public.api_keys SET activa = $2 WHERE tenant_id = $1", tenant_id, activo)
    await _recargar_registry()
    logger.info(f"[admin] tenant {tenant_id} {'activado' if activo else 'desactivado'}")
    return {"tenant_id": tenant_id, "activo": activo}
