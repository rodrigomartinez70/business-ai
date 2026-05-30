"""
API backend — Plataforma IA de Análisis de Negocio
Text-to-SQL agnóstico al modelo de datos.

Endpoints compatibles con Open WebUI:
  POST /api/v1/chat/completions
  Header: Authorization: Bearer <API_KEY_POR_ROL>
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
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

    for i in range(10):
        try:
            config.db_pool = await asyncpg.create_pool(
                config.DATABASE_URL, min_size=2, max_size=10
            )
            logger.info("Conexión a PostgreSQL establecida.")
            break
        except Exception as e:
            logger.warning(f"Esperando PostgreSQL... ({i+1}/10): {e}")
            await asyncio.sleep(3)
    else:
        raise RuntimeError("No se pudo conectar a PostgreSQL.")

    config.SCHEMA_CACHE = await build_schema_cache(config.db_pool, config.CONFIG)
    logger.info(f"Schema cache construido para roles: {list(config.SCHEMA_CACHE.keys())}")

    _warn_placeholders(config.CONFIG)

    if config.INGEST_DATABASE_URL:
        config.ingest_pool = await asyncpg.create_pool(
            config.INGEST_DATABASE_URL, min_size=1, max_size=3
        )
        logger.info("Pool de ingest conectado.")
    else:
        logger.warning("INGEST_DATABASE_URL no configurada — /api/ingest/* deshabilitado.")

    yield

    if config.db_pool:
        await config.db_pool.close()
    if config.ingest_pool:
        await config.ingest_pool.close()


app = FastAPI(
    title="API IA — Plataforma de Análisis de Negocio",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(reports.router)
app.include_router(agents.router)
app.include_router(ingest.router)
