#!/usr/bin/env python3
"""
Carga/actualiza las credenciales de Meta Ads de un tenant en public.integraciones.

El token se ingresa de forma OCULTA (getpass) → nunca queda en el historial ni en
los logs. Si no se pasa --cuenta-id, usa el token para LISTAR las cuentas
publicitarias accesibles y te deja elegir (así no hace falta buscar el act_... a mano).

Uso (dentro del container api, que tiene asyncpg + httpx):
    docker cp /opt/ia_hotel/scripts/set_meta_token.py negocio_api:/tmp/
    docker compose exec -it api python /tmp/set_meta_token.py --tenant-id inmobiliaria
"""

import argparse
import asyncio
import getpass
import os
import sys

import asyncpg
import httpx

GRAPH = "https://graph.facebook.com/v21.0"


async def _listar_cuentas(token: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(
            f"{GRAPH}/me/adaccounts",
            params={"fields": "account_id,name,account_status",
                    "access_token": token, "limit": 200},
        )
        r.raise_for_status()
        return r.json().get("data", [])


async def run(args: argparse.Namespace) -> None:
    db = args.db_url or os.environ.get("DATABASE_URL")
    if not db:
        print("ERROR: falta DATABASE_URL en el entorno.", file=sys.stderr)
        sys.exit(1)

    token = getpass.getpass("Pegá el token de Meta (no se mostrará): ").strip()
    if not token:
        print("ERROR: token vacío.", file=sys.stderr)
        sys.exit(1)

    cuenta = args.cuenta_id
    if not cuenta:
        print("Consultando las cuentas publicitarias del token…")
        try:
            cuentas = await _listar_cuentas(token)
        except Exception as e:
            print(f"ERROR consultando Meta (¿token vencido o sin permiso ads_read?): {e}",
                  file=sys.stderr)
            sys.exit(1)
        if not cuentas:
            print("El token no tiene cuentas publicitarias accesibles.", file=sys.stderr)
            sys.exit(1)
        print("\nCuentas disponibles:")
        for i, a in enumerate(cuentas):
            estado = a.get("account_status")
            print(f"  [{i}] act_{a['account_id']}  —  {a.get('name', '(sin nombre)')}"
                  f"  (status {estado})")
        idx = int(input("\nElegí el número de la cuenta a guardar: ").strip())
        cuenta = f"act_{cuentas[idx]['account_id']}"

    conn = await asyncpg.connect(db)
    try:
        await conn.execute(
            """INSERT INTO public.integraciones
                   (tenant_id, proveedor, access_token, cuenta_id, activo, actualizado_en)
               VALUES ($1, 'meta', $2, $3, TRUE, CURRENT_TIMESTAMP)
               ON CONFLICT (tenant_id, proveedor) DO UPDATE SET
                   access_token   = EXCLUDED.access_token,
                   cuenta_id      = EXCLUDED.cuenta_id,
                   activo         = TRUE,
                   actualizado_en = CURRENT_TIMESTAMP""",
            args.tenant_id, token, cuenta,
        )
    finally:
        await conn.close()

    print(f"\n✓ Credenciales de Meta guardadas para tenant '{args.tenant_id}' "
          f"(cuenta {cuenta}).")
    print(f"  Siguiente: sincronizar con  sync_meta_ads.py --tenant-id {args.tenant_id} --dias 90")


def main() -> None:
    p = argparse.ArgumentParser(description="Carga credenciales de Meta Ads de un tenant.")
    p.add_argument("--tenant-id", required=True, help="Tenant (ej. inmobiliaria)")
    p.add_argument("--cuenta-id", default=None,
                   help="Ad Account ID (act_...). Si se omite, se listan las cuentas del token.")
    p.add_argument("--db-url", default=None, help="DATABASE_URL (default: env)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
