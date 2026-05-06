"""
Fixtures compartidas para todos los tests.

Separación de scopes para evitar el "attached to a different loop" de asyncpg:
  - Config/API_KEYS: sync, session — no tiene event loop, se puede compartir.
  - DB pools: async, function — se crean en el mismo loop que el test que los usa.
"""

import os

# Deben estar antes de cualquier import del app
os.environ.setdefault("DATABASE_URL",          "postgresql://test_admin:test_password@localhost:5435/test_negocio_db")
os.environ.setdefault("INGEST_DATABASE_URL",   "postgresql://test_admin:test_password@localhost:5435/test_negocio_db")
os.environ.setdefault("BUSINESS_CONFIG_PATH",  "api/config.yaml")
os.environ.setdefault("API_KEY_GERENTE",       "test-key-gerente")
os.environ.setdefault("API_KEY_ADMINISTRACION","test-key-admin")
os.environ.setdefault("API_KEY_RECEPCION",     "test-key-recepcion")
os.environ.setdefault("ANTHROPIC_API_KEY",     "")
os.environ.setdefault("OLLAMA_URL",            "http://localhost:11434")

import pytest
import pytest_asyncio
import asyncpg
from httpx import ASGITransport, AsyncClient

from src import config
from src.main import app
from src.schema import build_schema_cache


# ── Config: sync, session ─────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _load_config():
    """Carga config.yaml y construye API_KEYS una sola vez."""
    config.CONFIG   = config.load_config()
    config.API_KEYS = config.build_api_keys(config.CONFIG)


# ── DB pools: async, function ─────────────────────────────────────────────────
# Se crean en el mismo event loop que el test → no hay mismatch.

@pytest_asyncio.fixture(autouse=True)
async def _db_pools(_load_config):
    """Crea y destruye los pools para cada test."""
    config.db_pool = await asyncpg.create_pool(
        config.DATABASE_URL, min_size=1, max_size=3
    )
    config.SCHEMA_CACHE = await build_schema_cache(config.db_pool, config.CONFIG)

    if config.INGEST_DATABASE_URL:
        config.ingest_pool = await asyncpg.create_pool(
            config.INGEST_DATABASE_URL, min_size=1, max_size=3
        )

    yield

    await config.db_pool.close()
    config.db_pool = None
    if config.ingest_pool:
        await config.ingest_pool.close()
        config.ingest_pool = None


# ── Cliente HTTP ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(_db_pools):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── Headers de autenticación ──────────────────────────────────────────────────

@pytest.fixture
def gerente_headers():
    return {"Authorization": f"Bearer {os.environ['API_KEY_GERENTE']}"}


@pytest.fixture
def recepcion_headers():
    return {"Authorization": f"Bearer {os.environ['API_KEY_RECEPCION']}"}
