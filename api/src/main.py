"""
API backend — Plataforma IA de Análisis de Negocio
Text-to-SQL agnóstico al modelo de datos.

Endpoints compatibles con Open WebUI:
  POST /api/v1/chat/completions
  Header: Authorization: Bearer <API_KEY_POR_ROL>
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config, tenant_registry
from .db import TenantAwarePool
from .routers import agents, chat, ingest, reports
from .schema import build_schema_cache

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_DEFAULT_PLACEHOLDERS = {"Mi Negocio", "negocio", ""}


def _warn_placeholders(cfg: dict) -> None:
    biz_name = cfg.get("business", {}).get("name", "")
    if biz_name in _DEFAULT_PLACEHOLDERS:
        logger.warning(
            "⚠️  business.name en config.yaml todavía tiene el valor por defecto %r. "
            "Actualizalo con el nombre real del negocio.",
            biz_name,
        )
    for role in cfg.get("roles", []):
        default_key = role.get("default_key", "")
        if default_key and (default_key.endswith("_cambia_esto") or default_key.endswith("_change_me")):
            logger.warning(
                "⚠️  El rol %r usa la API key por defecto %r. "
                "Definí %s en .env con una clave segura.",
                role["name"], default_key, role["env_key"],
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.CONFIG   = config.load_config()
    config.API_KEYS = config.build_api_keys(config.CONFIG)

    # Pool raw — solo para lifespan (registry, schema cache).
    # Los requests usan config.db_pool que es un TenantAwarePool sobre este mismo pool.
    raw_pool = None
    for i in range(10):
        try:
            raw_pool = await asyncpg.create_pool(
                config.DATABASE_URL, min_size=2, max_size=10
            )
            logger.info("Conexión a PostgreSQL establecida.")
            break
        except Exception as e:
            logger.warning(f"Esperando PostgreSQL... ({i+1}/10): {e}")
            await asyncio.sleep(3)
    else:
        raise RuntimeError("No se pudo conectar a PostgreSQL.")

    # Schema cache global — fallback para tests sin fixture y modo legado
    config.SCHEMA_CACHE = await build_schema_cache(raw_pool, config.CONFIG)
    logger.info(f"Schema cache construido para roles: {list(config.SCHEMA_CACHE.keys())}")

    # Registry de tenants — usa raw_pool para queries a public.tenants / public.api_keys
    await tenant_registry.load_all_tenants(
        pool             = raw_pool,
        legacy_api_keys  = config.API_KEYS,
        legacy_config    = config.CONFIG,
        legacy_tenant_id = "hotel_mbi",
    )

    # Wrapear el pool: a partir de aquí todos los acquire() inyectan search_path
    config.db_pool = TenantAwarePool(raw_pool)

    _warn_placeholders(config.CONFIG)

    raw_ingest_pool = None
    if config.INGEST_DATABASE_URL:
        raw_ingest_pool = await asyncpg.create_pool(
            config.INGEST_DATABASE_URL, min_size=1, max_size=3
        )
        config.ingest_pool = TenantAwarePool(raw_ingest_pool)
        logger.info("Pool de ingest conectado.")
    else:
        logger.warning("INGEST_DATABASE_URL no configurada — /api/ingest/* deshabilitado.")

    yield

    await raw_pool.close()
    if raw_ingest_pool:
        await raw_ingest_pool.close()


app = FastAPI(
    title="API IA — Plataforma de Análisis de Negocio",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

_cors_origins_raw = os.getenv("CORS_ALLOWED_ORIGINS", "*")
_cors_origins     = [o.strip() for o in _cors_origins_raw.split(",")] if _cors_origins_raw != "*" else ["*"]

if "*" in _cors_origins:
    logger.warning(
        "⚠️  CORS configurado con origin '*'. "
        "En producción definí CORS_ALLOWED_ORIGINS con los dominios permitidos."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(chat.router)
app.include_router(reports.router)
app.include_router(agents.router)
app.include_router(ingest.router)
