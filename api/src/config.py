"""
Estado global de la aplicación y carga de configuración de negocio.

Todos los módulos importan desde aquí para evitar dependencias circulares.
El estado mutable (db_pool, CONFIG, etc.) se popula en el lifespan de main.py.
"""

import os
import yaml
import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

# ─── Variables de entorno ────────────────────────────────────

DATABASE_URL        = os.getenv("DATABASE_URL", "postgresql://negocio_user:negocio_password_change_me@postgres:5432/negocio_db")
INGEST_DATABASE_URL = os.getenv("INGEST_DATABASE_URL", "")   # vacío = ingest deshabilitado
OLLAMA_URL          = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL        = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
ANTHROPIC_KEY       = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL        = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5")
CONFIG_PATH         = os.getenv("BUSINESS_CONFIG_PATH", "/app/config.yaml")

# ─── Estado mutable (poblado en lifespan) ───────────────────

db_pool:      Optional[asyncpg.Pool] = None
ingest_pool:  Optional[asyncpg.Pool] = None   # pool con permisos INSERT para el endpoint /ingest
CONFIG:       dict          = {}
API_KEYS:     dict[str, str] = {}
SCHEMA_CACHE: dict[str, str] = {}


# ─── Carga de config ─────────────────────────────────────────

def load_config() -> dict:
    for path in [CONFIG_PATH, "config.yaml"]:
        if os.path.exists(path):
            with open(path) as f:
                cfg = yaml.safe_load(f)
            logger.info(f"Config cargada desde: {path}")
            return cfg
    raise RuntimeError(f"No se encontró config.yaml (buscado en {CONFIG_PATH} y ./config.yaml)")


def build_api_keys(cfg: dict) -> dict[str, str]:
    return {
        os.getenv(role["env_key"], role.get("default_key", "")): role["name"]
        for role in cfg.get("roles", [])
        if os.getenv(role["env_key"], role.get("default_key", ""))
    }


# ─── Accessors del config (lectura en caliente) ──────────────

def biz(key: str, default: str = "") -> str:
    return CONFIG.get("business", {}).get(key, default)


def schema_for(rol: str) -> str:
    return SCHEMA_CACHE.get(rol, SCHEMA_CACHE.get("default", ""))


def aliases_text() -> str:
    aliases = CONFIG.get("table_aliases", {})
    if not aliases:
        return ""
    return "Aliases sugeridos: " + ", ".join(f"{t}→{a}" for t, a in aliases.items())


def kpis_text() -> str:
    kpis = CONFIG.get("kpis", [])
    if not kpis:
        return ""
    return "\n".join(["KPIs del dominio:"] + [f"- {k['name']}: {k['description']}" for k in kpis])


def currency_hint() -> str:
    cur  = CONFIG.get("currency", {})
    sym  = cur.get("symbol", "$")
    tsep = cur.get("thousands_separator", ".")
    dp   = cur.get("decimal_places", 0)
    if dp == 0:
        return f"Formato moneda: {sym}1{tsep}234{tsep}567 (sin decimales)"
    dsep = cur.get("decimal_separator", ",")
    return f"Formato moneda: {sym}1{tsep}234{tsep}567{dsep}{dp * '0'}"
