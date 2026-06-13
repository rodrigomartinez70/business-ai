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

from .. import config, packs as packs_mod, tenant_registry

logger = logging.getLogger(__name__)

_SRC_DIR = Path(__file__).resolve().parents[1]          # .../api/src
_TENANT_RE = re.compile(r"^[a-z][a-z0-9_]{2,59}$")       # slug seguro para nombre de schema

# Presets: plantillas reutilizables que el alta copia al config del tenant. Cada
# preset propone un set de packs (ajustable en la UI) y trae su config base.
# El `vertical` se mantiene como etiqueta de transición (ver doc/design-packs.md).
PRESETS: dict[str, dict] = {
    "restaurante": {
        "label": "Restaurante",
        "vertical": "restaurante",
        "packs": ["base", "pos_gastronomico", "erp"],
        "desc": "Punto de venta gastronómico, con gastos, facturas y contabilidad.",
    },
    "hotel": {
        "label": "Hotel",
        "vertical": "hotel",
        "packs": ["base", "pos_hotelero", "erp"],
        "desc": "Reservas y habitaciones, con gastos, facturas y contabilidad.",
    },
    "comercial": {
        "label": "Comercial / Genérico",
        "vertical": "comercial",
        "packs": ["base", "erp"],
        "desc": "Sin punto de venta (fábrica, servicios): gastos, facturas y P&L contable.",
    },
}


def presets_catalogo() -> list[dict]:
    return [{"id": pid, **p} for pid, p in PRESETS.items()]


def packs_catalogo() -> list[dict]:
    return [{"id": p.id, "label": p.label, "desc": p.descripcion}
            for p in packs_mod.catalogo()]


class AdminError(Exception):
    """Error de validación/operación de administración (se traduce a 400)."""


# Color por cantidad de módulos activos (10 verde → 0 rojo), un color por valor.
_COLOR_MODULOS = {
    10: "#15803d", 9: "#16a34a", 8: "#22c55e", 7: "#65a30d", 6: "#84cc16",
    5:  "#ca8a04", 4: "#d97706", 3: "#ea580c", 2: "#dc2626", 1: "#b91c1c", 0: "#7f1d1d",
}


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


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
    import asyncpg
    from ..finanzas.informe import MODULOS
    _SQL = """SELECT t.id, t.nombre, t.vertical, t.activo, t.created_at, t.config, {packs}
                  (t.config IS NOT NULL) AS config_en_db,
                  (SELECT COUNT(*) FROM public.api_keys k
                    WHERE k.tenant_id = t.id AND k.activa) AS keys_activas
             FROM public.tenants t
            ORDER BY t.created_at DESC, t.id"""
    try:
        rows = await config.raw_pool.fetch(_SQL.format(packs="t.packs,"))
    except asyncpg.UndefinedColumnError:        # pre-migración 011
        rows = await config.raw_pool.fetch(_SQL.format(packs=""))
    total = len(MODULOS)
    out = []
    for r in rows:
        d = dict(r)
        d["packs"] = list(d.get("packs") or [])
        cfg = d.pop("config")
        if cfg is not None and not isinstance(cfg, dict):
            cfg = json.loads(cfg)
        mods = ((cfg or {}).get("report") or {}).get("modulos") or {}
        # Sin config de módulos = todos activos (clave ausente = on).
        activos = sum(1 for c, _a, _t in MODULOS if mods.get(c, True))
        d["modulos_activos"] = activos
        d["modulos_total"] = total
        d["modulos_color"] = _COLOR_MODULOS.get(activos, "#6b7280")
        out.append(d)
    return out


# ─────────────────────────────────────────────────────────────
# Alta
# ─────────────────────────────────────────────────────────────

async def crear(*, tenant_id: str, nombre: str, preset: str,
                packs: list[str] | None = None,
                email_to: list[str] | None = None) -> dict:
    tenant_id = (tenant_id or "").strip().lower()
    nombre    = (nombre or "").strip()
    preset    = (preset or "").strip().lower()
    email_to  = email_to or []

    if not _TENANT_RE.match(tenant_id):
        raise AdminError("ID inválido: minúsculas, empieza con letra, 3-60 chars [a-z0-9_].")
    if preset not in PRESETS:
        raise AdminError(f"Preset inválido. Opciones: {', '.join(PRESETS)}.")
    if not nombre:
        raise AdminError("El nombre de la empresa es obligatorio.")

    p = PRESETS[preset]
    vertical = p["vertical"]
    # Packs elegidos en la UI (ajustables); si no vienen, los del preset.
    # normalizar agrega 'base', deduplica y valida.
    try:
        packs = packs_mod.normalizar(packs or p["packs"])
    except packs_mod.PackError as e:
        raise AdminError(str(e))

    existe = await config.raw_pool.fetchval(
        "SELECT 1 FROM public.tenants WHERE id = $1", tenant_id)
    if existe:
        raise AdminError(f"Ya existe una empresa con id '{tenant_id}'.")

    # El schema se ensambla desde los packs de datos (única fuente de verdad).
    schema_ddl = packs_mod.schema_ddl(packs)
    cfg = _construir_config(nombre, vertical, email_to)
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
            """INSERT INTO public.tenants (id, nombre, vertical, config_path, config, packs, activo)
               VALUES ($1, $2, $3, $4, $5::jsonb, $6, TRUE)""",
            tenant_id, nombre, vertical, f"/app/tenants/{tenant_id}/config.yaml",
            json.dumps(cfg), packs)
        await conn.execute(
            """INSERT INTO public.api_keys (key_hash, tenant_id, rol, descripcion, activa)
               VALUES ($1, $2, 'gerente', $3, TRUE)""",
            hash_key(api_key), tenant_id, f"gerente — {tenant_id}")

    await _recargar_registry()
    logger.info(f"[admin] tenant creado: {tenant_id} ({vertical}, packs={packs})")
    # La API key se devuelve UNA sola vez (solo se guarda su hash).
    return {"tenant_id": tenant_id, "vertical": vertical, "packs": packs, "api_key": api_key}


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


async def eliminar(tenant_id: str) -> dict:
    """Elimina una empresa: filas de control (api_keys, integraciones, schedules) +
    DROP SCHEMA con todos sus datos. IRREVERSIBLE. Recarga el registry."""
    tenant_id = (tenant_id or "").strip().lower()
    if not _TENANT_RE.match(tenant_id):                      # anti-inyección en DROP SCHEMA
        raise AdminError("ID de empresa inválido.")
    if not await config.raw_pool.fetchval("SELECT 1 FROM public.tenants WHERE id = $1", tenant_id):
        raise AdminError(f"No existe la empresa '{tenant_id}'.")
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM public.api_keys WHERE tenant_id = $1", tenant_id)
            await conn.execute("DELETE FROM public.integraciones WHERE tenant_id = $1", tenant_id)
            await conn.execute("DELETE FROM public.report_schedules WHERE tenant_id = $1", tenant_id)
            await conn.execute("DELETE FROM public.tenants WHERE id = $1", tenant_id)
            await conn.execute(f'DROP SCHEMA IF EXISTS "{tenant_id}" CASCADE')
    await _recargar_registry()
    logger.warning(f"[admin] EMPRESA ELIMINADA: {tenant_id}")
    return {"tenant_id": tenant_id}


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
