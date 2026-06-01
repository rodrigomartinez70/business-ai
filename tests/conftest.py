"""
Fixtures compartidas para todos los tests.

Separación de scopes para evitar el "attached to a different loop" de asyncpg:
  - Config/API_KEYS: sync, session — no tiene event loop, se puede compartir.
  - DB pools + TenantContext: async, function — se crean en el mismo loop que el test.

Multi-tenancy en tests:
  - tenant_id = "hotel_mbi" (si el schema existe post-migración, se usa directamente;
    si todavía está en public, PostgreSQL lo ignora silenciosamente y usa public).
  - El registry se carga con las keys de test antes de cada test.
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

from src import config, tenant_registry
from src.db import TenantAwarePool
from src.main import app
from src.schema import build_schema_cache, build_schema_cache_for_tenant
from src.tenant import TenantContext, reset_tenant, set_tenant

_TEST_TENANT_ID = "hotel_mbi"


# ── Config: sync, session ─────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _load_config():
    """Carga config.yaml y construye API_KEYS una sola vez."""
    config.CONFIG   = config.load_config()
    config.API_KEYS = config.build_api_keys(config.CONFIG)


# ── DB pools + TenantContext: async, function ─────────────────────────────────

@pytest_asyncio.fixture(autouse=True)
async def _db_pools(_load_config):
    """
    Crea el raw pool, buildea el schema cache, setea el TenantContext
    y wrapea los pools con TenantAwarePool para cada test.

    TenantAwarePool emite SET search_path = hotel_mbi, public.
    Si hotel_mbi no existe (pre-migración), PostgreSQL lo ignora
    silenciosamente y resuelve las tablas desde public.
    """
    raw_pool = await asyncpg.create_pool(
        config.DATABASE_URL, min_size=1, max_size=3
    )

    # Schema cache — intenta hotel_mbi, cae a public si no existe
    try:
        schema_cache = await build_schema_cache_for_tenant(
            raw_pool, config.CONFIG, _TEST_TENANT_ID
        )
    except Exception:
        schema_cache = await build_schema_cache(raw_pool, config.CONFIG)

    config.SCHEMA_CACHE = schema_cache

    # TenantContext de test
    test_ctx = TenantContext(
        tenant_id    = _TEST_TENANT_ID,
        rol          = "gerente",
        vertical     = config.CONFIG.get("business", {}).get("vertical", "hotel"),
        config       = config.CONFIG,
        schema_cache = schema_cache,
    )

    # Setear el contextvar para que get_tenant() funcione en el código llamado
    tenant_token = set_tenant(test_ctx)

    # Wrapear pool — a partir de aquí acquire() inyecta SET search_path
    config.db_pool = TenantAwarePool(raw_pool)

    # Poblar el registry con las keys de test para que auth.py resuelva correctamente
    await tenant_registry.load_all_tenants(
        pool             = raw_pool,
        legacy_api_keys  = config.API_KEYS,
        legacy_config    = config.CONFIG,
        legacy_tenant_id = _TEST_TENANT_ID,
    )

    raw_ingest_pool = None
    if config.INGEST_DATABASE_URL:
        raw_ingest_pool = await asyncpg.create_pool(
            config.INGEST_DATABASE_URL, min_size=1, max_size=3
        )
        config.ingest_pool = TenantAwarePool(raw_ingest_pool)

    yield

    reset_tenant(tenant_token)

    await raw_pool.close()
    config.db_pool = None
    if raw_ingest_pool:
        await raw_ingest_pool.close()
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
