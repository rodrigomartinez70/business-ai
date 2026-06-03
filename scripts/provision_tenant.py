#!/usr/bin/env python3
"""
Provisiona un nuevo tenant en el sistema multi-tenant.

──────────────────────────────────────────────────────────────
MODO COMPLETO (DB + Open WebUI + Caddy):
    python scripts/provision_tenant.py \\
        --tenant-id restaurante_xyz \\
        --nombre "Restaurante XYZ" \\
        --vertical restaurante \\
        --base-domain majorbi.com \\
        --api-key-gerente $(openssl rand -hex 32)
    # → genera subdominio: restaurante-xyz.majorbi.com

    # O con dominio explícito:
    python scripts/provision_tenant.py \\
        --tenant-id restaurante_xyz \\
        --nombre "Restaurante XYZ" \\
        --vertical restaurante \\
        --dominio restaurante-xyz.majorbi.com \\
        --api-key-gerente $(openssl rand -hex 32)

SOLO DB (sin levantar Open WebUI):
    python scripts/provision_tenant.py \\
        --tenant-id restaurante_xyz \\
        --nombre "Restaurante XYZ" \\
        --vertical restaurante \\
        --api-key-gerente $(openssl rand -hex 32)

SOLO KEYS (tenant ya existe en DB, ej. MBI post-migración):
    python scripts/provision_tenant.py \\
        --tenant-id hotel_mbi \\
        --insert-keys-only \\
        --api-key-gerente <valor> \\
        --api-key-administracion <valor> \\
        --api-key-recepcion <valor>
──────────────────────────────────────────────────────────────

Lo que hace en modo completo:
  DB:
    1. Crea el schema PostgreSQL del tenant
    2. Ejecuta verticals/<vertical>/schema.sql en ese schema
    3. Otorga permisos a negocio_user y negocio_ingest
    4. Inserta en public.tenants
    5. Hashea e inserta las API keys en public.api_keys
    6. Genera api/tenants/{tenant_id}/config.yaml desde la plantilla del vertical

  Open WebUI (si se pasa --dominio):
    6. Escribe caddy/tenants/{tenant_id}.caddy con el bloque del subdominio
    7. Agrega el servicio open-webui-{tenant_id} a docker-compose.tenants.yml
    8. Levanta el container con docker compose
    9. Recarga Caddy

Variables de entorno requeridas (o pasar --db-url):
    DATABASE_URL  — conexión con permisos de CREATE SCHEMA

Después del script:
    - Apuntar DNS: {dominio} → IP del servidor
    - Crear /app/tenants/{tenant_id}/config.yaml (copiar de api/config.yaml)
    - docker compose restart api  (recarga el registry de tenants)
"""

import argparse
import asyncio
import hashlib
import os
import secrets
import subprocess
import sys
from pathlib import Path

import asyncpg
import yaml

_PROYECTO_DIR = Path(__file__).parent.parent


# ─────────────────────────────────────────────────────────────
# Hashing
# ─────────────────────────────────────────────────────────────

def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


# ─────────────────────────────────────────────────────────────
# DB provisioning
# ─────────────────────────────────────────────────────────────

def _schema_sql_path(vertical: str) -> Path:
    return _PROYECTO_DIR / "api" / "src" / "verticals" / vertical / "schema.sql"


def _config_template_path(vertical: str) -> Path:
    return _PROYECTO_DIR / "api" / "src" / "verticals" / vertical / "config.template.yaml"


def _generar_config(args: argparse.Namespace) -> None:
    """Genera api/tenants/<tenant_id>/config.yaml desde la plantilla del vertical."""
    template = Path(args.config_template) if args.config_template else _config_template_path(args.vertical)
    if not template.exists():
        print(f"  ⚠️  Plantilla no encontrada ({template}); config NO generada. "
              f"Crear manualmente /app/tenants/{args.tenant_id}/config.yaml.", file=sys.stderr)
        return

    with open(template) as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("business", {})
    if args.nombre:
        cfg["business"]["name"] = args.nombre
    cfg["business"]["vertical"] = args.vertical

    dest = _PROYECTO_DIR / "api" / "tenants" / args.tenant_id / "config.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"  ✓ Config generada: {dest}")


async def _provision_completo(conn: asyncpg.Connection, args: argparse.Namespace) -> None:
    tenant_id = args.tenant_id
    vertical  = args.vertical

    schema_path = _schema_sql_path(vertical)
    if not schema_path.exists():
        print(f"ERROR: no se encontró {schema_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\nProvisionando tenant '{tenant_id}' (vertical: {vertical})...")

    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{tenant_id}"')
    print(f"  ✓ Schema '{tenant_id}' creado.")

    async with conn.transaction():
        await conn.execute(f'SET LOCAL search_path = "{tenant_id}"')
        await conn.execute(schema_path.read_text())
    print(f"  ✓ Tablas creadas desde {schema_path.name}.")

    await _grant_permisos(conn, tenant_id)
    print(f"  ✓ Permisos otorgados a negocio_user y negocio_ingest.")

    config_path = args.config_path or f"/app/tenants/{tenant_id}/config.yaml"
    await conn.execute("""
        INSERT INTO public.tenants (id, nombre, vertical, config_path)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE
            SET nombre = EXCLUDED.nombre,
                vertical = EXCLUDED.vertical,
                config_path = EXCLUDED.config_path
    """, tenant_id, args.nombre, vertical, config_path)
    print(f"  ✓ Registrado en public.tenants.")

    await _insertar_keys(conn, args)

    _generar_config(args)


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
            pass


async def _insertar_keys(conn: asyncpg.Connection, args: argparse.Namespace) -> None:
    tenant_id = args.tenant_id
    insertadas = 0
    key_map = {
        "gerente":        getattr(args, "api_key_gerente",        None),
        "administracion": getattr(args, "api_key_administracion", None),
        "recepcion":      getattr(args, "api_key_recepcion",      None),
        "cajero":         getattr(args, "api_key_cajero",         None),
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
        print(f"  ✓ API key '{rol}' insertada.")
        insertadas += 1

    if insertadas == 0:
        print("  ⚠️  Sin API keys — proveer al menos --api-key-gerente.")


# ─────────────────────────────────────────────────────────────
# Open WebUI provisioning
# ─────────────────────────────────────────────────────────────

def _container_name(tenant_id: str) -> str:
    return f"open-webui-{tenant_id.replace('_', '-')}"


def _detectar_red() -> str:
    """Detecta la red Docker creada por docker-compose en el directorio del proyecto."""
    try:
        result = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True, text=True, check=True,
        )
        dir_name = _PROYECTO_DIR.name
        for line in result.stdout.splitlines():
            if line.startswith(dir_name) and "_default" in line:
                return line
    except Exception:
        pass
    return f"{_PROYECTO_DIR.name}_default"


def _escribir_caddy_tenant(tenant_id: str, container: str, dominio: str) -> None:
    tenants_dir = _PROYECTO_DIR / "caddy" / "tenants"
    tenants_dir.mkdir(parents=True, exist_ok=True)
    (tenants_dir / f"{tenant_id}.caddy").write_text(
        f"{dominio} {{\n    reverse_proxy {container}:8080\n}}\n"
    )
    print(f"  ✓ caddy/tenants/{tenant_id}.caddy creado.")


def _actualizar_compose_tenants(
    tenant_id: str,
    container: str,
    api_key: str,
    nombre: str,
    webui_secret: str,
    imagen: str,
    red: str,
) -> None:
    compose_path = _PROYECTO_DIR / "docker-compose.tenants.yml"
    volume_name  = f"open_webui_{tenant_id}_data"

    compose: dict = {}
    if compose_path.exists():
        with open(compose_path) as f:
            compose = yaml.safe_load(f) or {}

    compose.setdefault("services", {})
    compose.setdefault("volumes",  {})
    compose.setdefault("networks", {})

    compose["services"][container] = {
        "image":          imagen,
        "container_name": container,
        "restart":        "unless-stopped",
        "environment": [
            f"WEBUI_SECRET_KEY={webui_secret}",
            "WEBUI_AUTH=true",
            "ENABLE_SIGNUP=false",
            "ENABLE_OLLAMA_API=false",
            "OPENAI_API_BASE_URLS=http://negocio_api:8000/api/v1",
            f"OPENAI_API_KEYS={api_key}",
            f"WEBUI_NAME={nombre}",
            "SCARF_NO_ANALYTICS=true",
            "DO_NOT_TRACK=true",
            "ANONYMIZED_TELEMETRY=false",
        ],
        "volumes":  [f"{volume_name}:/app/backend/data"],
        "networks": [red],
    }
    compose["volumes"][volume_name] = None
    compose["networks"][red] = {"external": True}

    with open(compose_path, "w") as f:
        yaml.dump(compose, f, default_flow_style=False, allow_unicode=True)
    print(f"  ✓ docker-compose.tenants.yml actualizado.")


def _levantar_container(container: str) -> None:
    compose_path = _PROYECTO_DIR / "docker-compose.tenants.yml"
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_path), "up", "-d", container],
        cwd=str(_PROYECTO_DIR),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ⚠️  Error al levantar container:\n{result.stderr}", file=sys.stderr)
    else:
        print(f"  ✓ Container '{container}' levantado.")


def _recargar_caddy() -> None:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "caddy",
         "caddy", "reload", "--config", "/etc/caddy/Caddyfile"],
        cwd=str(_PROYECTO_DIR),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ⚠️  Caddy reload falló: {result.stderr}", file=sys.stderr)
    else:
        print(f"  ✓ Caddy recargado.")


def provision_webui(args: argparse.Namespace) -> None:
    tenant_id     = args.tenant_id
    nombre        = args.nombre
    dominio       = args.dominio
    api_key       = args.api_key_gerente or ""
    webui_secret  = args.webui_secret or secrets.token_hex(32)
    imagen        = args.webui_image
    container     = _container_name(tenant_id)
    red           = _detectar_red()

    print(f"\nLevantando Open WebUI para '{tenant_id}'...")
    print(f"  Red Docker:  {red}")
    print(f"  Container:   {container}")
    print(f"  Dominio:     {dominio}")

    _escribir_caddy_tenant(tenant_id, container, dominio)
    _actualizar_compose_tenants(tenant_id, container, api_key, nombre, webui_secret, imagen, red)
    _levantar_container(container)
    _recargar_caddy()

    print(f"\n  ✅  Open WebUI listo en http://{dominio}")
    print(f"  ⚠️  DNS pendiente: apuntar {dominio} → IP del servidor")
    print(f"  Config del tenant: api/tenants/{tenant_id}/config.yaml (generada).")
    print(f"  Después: docker compose restart api  (recarga el registry)")


# ─────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
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

    if args.dominio and not args.insert_keys_only:
        provision_webui(args)

    print("\n✅  Listo.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provisiona un tenant en el sistema multi-tenant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # DB
    parser.add_argument("--tenant-id",    required=True,  help="ID único del tenant (ej. restaurante_xyz)")
    parser.add_argument("--nombre",       default="",     help="Nombre visible del negocio")
    parser.add_argument("--vertical",     default="hotel", help="Vertical del negocio (default: hotel)")
    parser.add_argument("--config-path",  default=None,   help="Ruta al config.yaml dentro del container")
    parser.add_argument("--config-template", default=None, help="Plantilla de config (default: verticals/<vertical>/config.template.yaml)")
    parser.add_argument("--db-url",       default=None,   help="DATABASE_URL (default: var de entorno)")
    parser.add_argument("--insert-keys-only", action="store_true",
                        help="Solo inserta API keys, sin crear schema ni tablas")
    parser.add_argument("--api-key-gerente",        default=None)
    parser.add_argument("--api-key-administracion", default=None)
    parser.add_argument("--api-key-recepcion",      default=None, help="rol recepción (hotel)")
    parser.add_argument("--api-key-cajero",         default=None, help="rol cajero (restaurante)")

    # Open WebUI
    parser.add_argument("--dominio",      default=None,
                        help="Subdominio completo (ej. restaurante-xyz.majorbi.com). "
                             "Si se omite pero se pasa --base-domain, se genera automáticamente.")
    parser.add_argument("--base-domain",  default=None,
                        help="Dominio base de la plataforma (ej. majorbi.com). "
                             "Genera el subdominio como {tenant-id}.{base-domain}.")
    parser.add_argument("--webui-secret", default=None,
                        help="Secret key para Open WebUI (auto-generado si no se indica)")
    parser.add_argument("--webui-image",  default="ghcr.io/open-webui/open-webui:v0.9.5",
                        help="Imagen Docker de Open WebUI")

    args = parser.parse_args()

    if not args.insert_keys_only and not args.nombre:
        parser.error("--nombre es requerido en modo completo.")

    # Auto-generar subdominio desde --base-domain si no se pasó --dominio
    if args.base_domain and not args.dominio:
        slug = args.tenant_id.replace("_", "-")
        args.dominio = f"{slug}.{args.base_domain}"

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
