#!/usr/bin/env python3
"""
Provisiona un nuevo tenant en el sistema multi-tenant.

Uso básico (tenant nuevo completo):
    python scripts/provision_tenant.py \\
        --tenant-id hotel_abc \\
        --nombre "Hotel ABC" \\
        --vertical hotel \\
        --config-path /app/tenants/hotel_abc/config.yaml \\
        --api-key-gerente $(openssl rand -hex 32)

Uso para insertar keys en un tenant ya existente (ej. MBI post-migración):
    python scripts/provision_tenant.py \\
        --tenant-id hotel_mbi \\
        --insert-keys-only \\
        --api-key-gerente <valor del .env> \\
        --api-key-administracion <valor del .env> \\
        --api-key-recepcion <valor del .env>

Variables de entorno requeridas (o pasar --db-url):
    DATABASE_URL  — conexión como superuser o rol con CREATE SCHEMA

Lo que hace en modo completo:
    1. Crea el schema PostgreSQL del tenant
    2. Ejecuta el schema.sql de la vertical (crea tablas e índices)
    3. Otorga permisos a negocio_user y negocio_ingest
    4. Inserta en public.tenants
    5. Hashea e inserta las API keys en public.api_keys

Después del script: copiar y editar el config.yaml del tenant,
luego reiniciar el contenedor api para recargar el registry.
"""

import argparse
import asyncio
import hashlib
import os
import sys
from pathlib import Path

import asyncpg

# Roles estándar — pueden extenderse según el vertical
_ROLES_ESTANDAR = ["gerente", "administracion", "recepcion"]


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def _schema_sql_path(vertical: str) -> Path:
    """Ruta al schema.sql del vertical relativa a la raíz del repo."""
    base = Path(__file__).parent.parent
    return base / "api" / "src" / "verticals" / vertical / "schema.sql"


async def provision(args: argparse.Namespace) -> None:
    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: proveer --db-url o DATABASE_URL en el entorno.", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(db_url)

    try:
        if args.insert_keys_only:
            await _insertar_keys(conn, args)
        else:
            await _provision_completo(conn, args)
    finally:
        await conn.close()


async def _provision_completo(conn: asyncpg.Connection, args: argparse.Namespace) -> None:
    tenant_id = args.tenant_id
    vertical  = args.vertical

    schema_path = _schema_sql_path(vertical)
    if not schema_path.exists():
        print(f"ERROR: no se encontró {schema_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Provisioning tenant '{tenant_id}' (vertical: {vertical})...")

    # 1. Crear schema
    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"')
    print(f"  ✓ Schema '{tenant_id}' creado.")

    # 2. Ejecutar schema.sql de la vertical dentro del schema del tenant
    schema_sql = schema_path.read_text()
    async with conn.transaction():
        await conn.execute(f'SET LOCAL search_path = "{tenant_id}"')
        await conn.execute(schema_sql)
    print(f"  ✓ Tablas creadas desde {schema_path.name}.")

    # 3. Permisos
    await _grant_permisos(conn, tenant_id)
    print(f"  ✓ Permisos otorgados a negocio_user y negocio_ingest.")

    # 4. Insertar en public.tenants
    config_path = args.config_path or f"/app/tenants/{tenant_id}/config.yaml"
    await conn.execute("""
        INSERT INTO public.tenants (id, nombre, vertical, config_path)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE
            SET nombre = EXCLUDED.nombre,
                vertical = EXCLUDED.vertical,
                config_path = EXCLUDED.config_path
    """, tenant_id, args.nombre, vertical, config_path)
    print(f"  ✓ Tenant registrado en public.tenants.")

    # 5. Insertar keys
    await _insertar_keys(conn, args)

    print(f"\nTenant '{tenant_id}' provisionado correctamente.")
    print(f"\nPróximos pasos:")
    print(f"  1. Crear y editar {config_path} (copiar de api/config.yaml como base)")
    print(f"  2. docker compose restart api  — recarga el registry")


async def _grant_permisos(conn: asyncpg.Connection, tenant_id: str) -> None:
    perms = [
        f'GRANT USAGE ON SCHEMA "{tenant_id}" TO negocio_user',
        f'GRANT SELECT ON ALL TABLES IN SCHEMA "{tenant_id}" TO negocio_user',
        f'GRANT INSERT ON "{tenant_id}".audit_log TO negocio_user',
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{tenant_id}" TO negocio_user',
        f'GRANT USAGE ON SCHEMA "{tenant_id}" TO negocio_ingest',
        f'GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA "{tenant_id}" TO negocio_ingest',
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{tenant_id}" TO negocio_ingest',
    ]
    for stmt in perms:
        try:
            await conn.execute(stmt)
        except asyncpg.UndefinedObjectError:
            pass  # rol no existe en este entorno (ej. tests)


async def _insertar_keys(conn: asyncpg.Connection, args: argparse.Namespace) -> None:
    tenant_id = args.tenant_id
    keys_insertadas = 0

    key_map = {
        "gerente":       getattr(args, "api_key_gerente",       None),
        "administracion": getattr(args, "api_key_administracion", None),
        "recepcion":     getattr(args, "api_key_recepcion",     None),
    }

    for rol, api_key in key_map.items():
        if not api_key:
            continue
        await conn.execute("""
            INSERT INTO public.api_keys (key_hash, tenant_id, rol, descripcion)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (key_hash) DO UPDATE
                SET tenant_id   = EXCLUDED.tenant_id,
                    rol         = EXCLUDED.rol,
                    descripcion = EXCLUDED.descripcion,
                    activa      = TRUE
        """, hash_key(api_key), tenant_id, rol, f"{rol} — {tenant_id}")
        print(f"  ✓ API key para '{rol}' insertada (hash: {hash_key(api_key)[:16]}...).")
        keys_insertadas += 1

    if keys_insertadas == 0:
        print("  ⚠️  No se insertaron API keys — proveer al menos --api-key-gerente.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provisiona un tenant en el sistema multi-tenant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tenant-id",   required=True, help="ID único del tenant (ej. hotel_abc)")
    parser.add_argument("--nombre",      default="",    help="Nombre del negocio")
    parser.add_argument("--vertical",    default="hotel", help="Vertical del negocio (default: hotel)")
    parser.add_argument("--config-path", default=None,  help="Ruta al config.yaml dentro del container")
    parser.add_argument("--db-url",      default=None,  help="DATABASE_URL (default: var de entorno)")
    parser.add_argument("--insert-keys-only", action="store_true",
                        help="Solo inserta API keys, no crea schema ni tablas")
    parser.add_argument("--api-key-gerente",       default=None)
    parser.add_argument("--api-key-administracion", default=None)
    parser.add_argument("--api-key-recepcion",     default=None)

    args = parser.parse_args()

    if not args.insert_keys_only and not args.nombre:
        parser.error("--nombre es requerido en modo completo.")

    asyncio.run(provision(args))


if __name__ == "__main__":
    main()
