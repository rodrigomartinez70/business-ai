"""
Registry en memoria de tenants activos.

Al arrancar (lifespan), carga todos los tenants desde public.tenants
y construye dos índices:
  - _TENANT_INDEX:  tenant_id → TenantContext base (sin rol)
  - _KEY_INDEX:     SHA-256(api_key) → TenantContext con rol

Las API keys se guardan hasheadas (SHA-256) — nunca en texto plano.
El lookup por request es O(1) sin queries a DB.

Modo legado: si public.tenants está vacío, cae al config.yaml y API
keys de env vars (compatible con deployments single-tenant existentes).
"""

import hashlib
import logging
import yaml
import asyncpg
from typing import Optional

from .tenant import TenantContext
from .schema import build_schema_cache_for_tenant

logger = logging.getLogger(__name__)

# Índice principal de autenticación: SHA-256(api_key) → TenantContext con rol
_KEY_INDEX: dict[str, TenantContext] = {}

# Índice secundario: tenant_id → TenantContext base (para admin/provisioning)
_TENANT_INDEX: dict[str, TenantContext] = {}


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def resolve_api_key(api_key: str) -> Optional[TenantContext]:
    """Retorna el TenantContext (con rol) asociado a la API key, o None."""
    return _KEY_INDEX.get(hash_key(api_key))


def get_tenant_by_id(tenant_id: str) -> Optional[TenantContext]:
    return _TENANT_INDEX.get(tenant_id)


def all_tenant_ids() -> list[str]:
    return list(_TENANT_INDEX.keys())


async def load_all_tenants(
    pool: asyncpg.Pool,
    legacy_api_keys: dict[str, str],
    legacy_config: dict,
    legacy_tenant_id: str = "hotel_mbi",
) -> None:
    """
    Carga todos los tenants desde public.tenants y construye los índices.

    Recibe el pool RAW (asyncpg.Pool, no TenantAwarePool) porque las queries
    de control van a public.tenants / public.api_keys, fuera del search_path
    de los tenants.

    Si public.tenants está vacío, activa el modo legado: un solo tenant
    construido desde el config.yaml y las API keys del .env.
    """
    global _KEY_INDEX, _TENANT_INDEX

    _KEY_INDEX    = {}
    _TENANT_INDEX = {}

    rows = await pool.fetch(
        "SELECT id, nombre, vertical, config_path FROM public.tenants WHERE activo = TRUE"
    )

    if not rows:
        logger.warning(
            "public.tenants vacío — modo legado (single-tenant). "
            "Ejecutar 001_control.sql y 002_migrate_mbi.sql para migrar."
        )
        await _load_legacy_tenant(pool, legacy_api_keys, legacy_config, legacy_tenant_id)
        return

    for row in rows:
        tenant_id   = row["id"]
        config_path = row["config_path"]
        vertical    = row["vertical"]

        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"No se pudo cargar config del tenant '{tenant_id}' ({config_path}): {e}")
            continue

        try:
            schema_cache = await build_schema_cache_for_tenant(pool, cfg, tenant_id)
        except Exception as e:
            logger.error(f"No se pudo construir schema cache para '{tenant_id}': {e}")
            continue

        base_ctx = TenantContext(
            tenant_id    = tenant_id,
            rol          = "",          # se completa al indexar cada key
            vertical     = vertical,
            config       = cfg,
            schema_cache = schema_cache,
        )
        _TENANT_INDEX[tenant_id] = base_ctx

    key_rows = await pool.fetch(
        "SELECT key_hash, tenant_id, rol FROM public.api_keys WHERE activa = TRUE"
    )
    for kr in key_rows:
        base_ctx = _TENANT_INDEX.get(kr["tenant_id"])
        if not base_ctx:
            logger.warning(f"API key apunta a tenant desconocido: {kr['tenant_id']}")
            continue
        import dataclasses
        ctx = dataclasses.replace(base_ctx, rol=kr["rol"])
        _KEY_INDEX[kr["key_hash"]] = ctx

    logger.info(
        f"Registry cargado: {len(_TENANT_INDEX)} tenant(s), {len(_KEY_INDEX)} API key(s)."
    )


async def _load_legacy_tenant(
    pool: asyncpg.Pool,
    api_keys: dict[str, str],
    cfg: dict,
    tenant_id: str,
) -> None:
    """Modo legado: construye el registry desde config.yaml y env vars."""
    import dataclasses

    vertical = cfg.get("business", {}).get("vertical", "hotel")

    try:
        schema_cache = await build_schema_cache_for_tenant(pool, cfg, tenant_id)
    except Exception:
        # Si el schema todavía está en public (pre-migración), usar build_schema_cache
        from .schema import build_schema_cache
        schema_cache = await build_schema_cache(pool, cfg)

    base_ctx = TenantContext(
        tenant_id    = tenant_id,
        rol          = "",
        vertical     = vertical,
        config       = cfg,
        schema_cache = schema_cache,
    )
    _TENANT_INDEX[tenant_id] = base_ctx

    for api_key, rol in api_keys.items():
        if not api_key:
            continue
        ctx = dataclasses.replace(base_ctx, rol=rol)
        _KEY_INDEX[hash_key(api_key)] = ctx

    logger.info(
        f"Registry legado: tenant='{tenant_id}', vertical='{vertical}', "
        f"{len(api_keys)} API key(s)."
    )
