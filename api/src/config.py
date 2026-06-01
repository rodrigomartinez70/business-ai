"""
Estado global de la aplicación y carga de configuración de negocio.

Todos los módulos importan desde aquí para evitar dependencias circulares.
El estado mutable (db_pool, CONFIG, etc.) se popula en el lifespan de main.py.
"""

import os
import yaml
import logging
from typing import Optional

import anthropic
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

# ─── Canal de envío de reportes ──────────────────────────────
# REPORT_CHANNEL: "email" (dashboard HTML por correo) o "none" (no enviar).
REPORT_CHANNEL      = os.getenv("REPORT_CHANNEL", "email").strip().lower()
BUSINESS_VERTICAL   = os.getenv("BUSINESS_VERTICAL", "hotel").strip().lower()

# SMTP (envío del dashboard semanal por correo)
SMTP_HOST       = os.getenv("SMTP_HOST", "")
SMTP_PORT       = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_TLS    = os.getenv("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes")
SMTP_FROM       = os.getenv("SMTP_FROM", "") or SMTP_USER
REPORT_EMAIL_TO = os.getenv("REPORT_EMAIL_TO", "")   # coma-separado para varios destinatarios


def email_disponible() -> bool:
    """True si hay configuración SMTP mínima para enviar correos."""
    return bool(SMTP_HOST and SMTP_FROM and REPORT_EMAIL_TO)

# ─── Estado mutable (poblado en lifespan) ───────────────────

db_pool:      Optional[object] = None   # TenantAwarePool en runtime, asyncpg.Pool en tests/legado
ingest_pool:  Optional[object] = None   # ídem, con permisos INSERT para el endpoint /ingest
CONFIG:       dict          = {}
API_KEYS:     dict[str, str] = {}
SCHEMA_CACHE: dict[str, str] = {}


# ─── Cliente LLM (Claude) ────────────────────────────────────

_PLACEHOLDER_KEY = "sk-ant-tu-clave-aqui"
_anthropic_client: Optional[anthropic.AsyncAnthropic] = None


def claude_disponible() -> bool:
    """True si hay una API key de Claude real configurada (no el placeholder)."""
    return bool(ANTHROPIC_KEY) and ANTHROPIC_KEY != _PLACEHOLDER_KEY


def get_anthropic_client() -> anthropic.AsyncAnthropic:
    """
    Cliente Anthropic singleton — reutiliza el pool httpx y el keep-alive TLS
    entre requests en vez de recrearlo en cada llamada.
    """
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)
    return _anthropic_client


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


# ─── Accessors del config (tenant-aware) ────────────────────
# Dentro de un request delegan al TenantContext activo.
# Fuera de request (lifespan, tests sin fixture) usan el CONFIG global.

def get_config() -> dict:
    from .tenant import get_tenant_or_none
    ctx = get_tenant_or_none()
    return ctx.config if ctx is not None else CONFIG


def biz(key: str, default: str = "") -> str:
    from .tenant import get_tenant_or_none
    ctx = get_tenant_or_none()
    if ctx is not None:
        return ctx.biz(key, default)
    return CONFIG.get("business", {}).get(key, default)


def schema_for(rol: str) -> str:
    from .tenant import get_tenant_or_none
    ctx = get_tenant_or_none()
    if ctx is not None:
        return ctx.schema_for(rol)
    return SCHEMA_CACHE.get(rol, SCHEMA_CACHE.get("default", ""))


def aliases_text() -> str:
    from .tenant import get_tenant_or_none
    ctx = get_tenant_or_none()
    if ctx is not None:
        return ctx.aliases_text()
    aliases = CONFIG.get("table_aliases", {})
    if not aliases:
        return ""
    return "Aliases sugeridos: " + ", ".join(f"{t}→{a}" for t, a in aliases.items())


def kpis_text() -> str:
    from .tenant import get_tenant_or_none
    ctx = get_tenant_or_none()
    if ctx is not None:
        return ctx.kpis_text()
    kpis = CONFIG.get("kpis", [])
    if not kpis:
        return ""
    return "\n".join(["KPIs del dominio:"] + [f"- {k['name']}: {k['description']}" for k in kpis])


def currency_hint() -> str:
    from .tenant import get_tenant_or_none
    ctx = get_tenant_or_none()
    if ctx is not None:
        return ctx.currency_hint()
    cur  = CONFIG.get("currency", {})
    sym  = cur.get("symbol", "$")
    tsep = cur.get("thousands_separator", ".")
    dp   = cur.get("decimal_places", 0)
    if dp == 0:
        return f"Formato moneda: {sym}1{tsep}234{tsep}567 (sin decimales)"
    dsep = cur.get("decimal_separator", ",")
    return f"Formato moneda: {sym}1{tsep}234{tsep}567{dsep}{dp * '0'}"
