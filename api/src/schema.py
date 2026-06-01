"""
Introspección del schema de PostgreSQL vía information_schema.
Construye el texto de schema que recibe el LLM, enriquecido con
anotaciones del config.yaml.
"""

import logging
import asyncpg

logger = logging.getLogger(__name__)

_PG_TYPE_MAP = {
    "INTEGER": "INTEGER", "BIGINT": "BIGINT", "SMALLINT": "INTEGER",
    "NUMERIC": "NUMERIC", "REAL": "NUMERIC", "DOUBLE PRECISION": "NUMERIC",
    "CHARACTER VARYING": "TEXT", "CHARACTER": "TEXT", "TEXT": "TEXT",
    "BOOLEAN": "BOOLEAN", "DATE": "DATE",
    "TIMESTAMP WITHOUT TIME ZONE": "TIMESTAMP", "TIMESTAMP WITH TIME ZONE": "TIMESTAMP",
    "USER-DEFINED": "ENUM",
}


async def _fetch_tables(pool: asyncpg.Pool, exclude: set[str], schema: str = "public") -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = $1 AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """, schema)
    return [r["table_name"] for r in rows if r["table_name"] not in exclude]


async def _fetch_columns(
    pool: asyncpg.Pool, tables: list[str], schema: str = "public"
) -> dict[str, list[dict]]:
    if not tables:
        return {}
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = ANY($2)
            ORDER BY table_name, ordinal_position
        """, schema, tables)
    result: dict[str, list[dict]] = {}
    for r in rows:
        result.setdefault(r["table_name"], []).append({
            "name": r["column_name"],
            "type": r["data_type"].upper(),
        })
    return result


async def _fetch_foreign_keys(pool: asyncpg.Pool, schema: str = "public") -> dict[tuple, tuple]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT kcu.table_name, kcu.column_name,
                   ccu.table_name AS ref_table, ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema   = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.table_schema   = ccu.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema    = $1
        """, schema)
    return {
        (r["table_name"], r["column_name"]): (r["ref_table"], r["ref_column"])
        for r in rows
    }


def _build_schema_text(
    tables: list[str],
    columns: dict[str, list[dict]],
    fks: dict[tuple, tuple],
    annotations: dict,
    kpis: list[dict],
    role_excluded: set[str],
) -> str:
    lines = ["Tablas disponibles en PostgreSQL:\n"]
    for table in tables:
        if table in role_excluded:
            continue
        ann      = annotations.get(table, {})
        ann_cols = ann.get("columns", {})
        header   = table + ":"
        if ann.get("description"):
            header += f"  -- {ann['description']}"
        lines.append(header)
        for col in columns.get(table, []):
            name   = col["name"]
            typ    = _PG_TYPE_MAP.get(col["type"], col["type"])
            fk     = fks.get((table, name))
            hints  = []
            if fk:
                hints.append(f"FK → {fk[0]}.{fk[1]}")
            if name in ann_cols:
                hints.append(ann_cols[name])
            suffix = ("  -- " + " | ".join(hints)) if hints else ""
            lines.append(f"  {name:<22}{typ}{suffix}")
        lines.append("")

    if kpis:
        lines.append("KPIs importantes:")
        for kpi in kpis:
            lines.append(f"- {kpi['name']}: {kpi['description']}")

    return "\n".join(lines)


def _build_cache_from_data(
    cfg: dict,
    all_tables: list[str],
    columns: dict,
    fks: dict,
) -> dict[str, str]:
    """Construye el dict {rol: schema_text} a partir de datos ya fetched."""
    schema_cfg  = cfg.get("schema", {})
    global_excl = set(schema_cfg.get("exclude_tables", []))
    annotations = schema_cfg.get("annotations", {})
    kpis        = cfg.get("kpis", [])

    cache: dict[str, str] = {}
    for role in cfg.get("roles", []):
        role_excl = global_excl | set(role.get("excluded_tables", []))
        cache[role["name"]] = _build_schema_text(
            all_tables, columns, fks, annotations, kpis, role_excl
        )
    cache["default"] = _build_schema_text(
        all_tables, columns, fks, annotations, kpis, global_excl
    )
    return cache


async def build_schema_cache(pool: asyncpg.Pool, cfg: dict) -> dict[str, str]:
    """Construye el schema cache para el schema 'public' (modo single-tenant / legado)."""
    schema_cfg  = cfg.get("schema", {})
    global_excl = set(schema_cfg.get("exclude_tables", []))

    all_tables = await _fetch_tables(pool, global_excl)
    columns    = await _fetch_columns(pool, all_tables)
    fks        = await _fetch_foreign_keys(pool)

    cache = _build_cache_from_data(cfg, all_tables, columns, fks)
    logger.info(f"Schema cache construido para roles: {list(cache.keys())}")
    return cache


async def build_schema_cache_for_tenant(
    pool: asyncpg.Pool,
    cfg: dict,
    tenant_schema: str,
) -> dict[str, str]:
    """
    Construye el schema cache para el schema de un tenant específico.
    Usa el mismo pool raw (sin TenantAwarePool) para no interferir con
    conexiones de request en curso.
    """
    schema_cfg  = cfg.get("schema", {})
    global_excl = set(schema_cfg.get("exclude_tables", []))

    all_tables = await _fetch_tables(pool, global_excl, schema=tenant_schema)
    columns    = await _fetch_columns(pool, all_tables, schema=tenant_schema)
    fks        = await _fetch_foreign_keys(pool, schema=tenant_schema)

    cache = _build_cache_from_data(cfg, all_tables, columns, fks)
    logger.info(f"Schema cache construido para tenant '{tenant_schema}': roles {list(cache.keys())}")
    return cache
