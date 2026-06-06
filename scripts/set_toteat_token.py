#!/usr/bin/env python3
"""
Carga/actualiza las credenciales de Toteat de un tenant en public.integraciones.

El token se ingresa OCULTO (getpass) → no queda en el historial ni en logs. Antes de
guardar, valida las credenciales contra el endpoint liviano /shiftstatus de Toteat.

Toteat se autentica con 4 valores (te los da Toteat): xapitoken (token), xir
(restaurante), xil (local), xiu (usuario).

Uso (dentro del container api, que tiene asyncpg + httpx):
    docker cp /opt/ia_hotel/scripts/set_toteat_token.py negocio_api:/tmp/
    docker compose exec -it api python /tmp/set_toteat_token.py \\
        --tenant-id restaurante_toteat --xir <R> --xil <L> --xiu <U>
"""

import argparse
import asyncio
import getpass
import json
import os
import sys

import asyncpg
import httpx

BASE_DEFAULT = "https://api.toteat.com/mw/or/1.0/"


async def _validar(base: str, token: str, xir: str, xil: str, xiu: str):
    url = base.rstrip("/") + "/shiftstatus"
    params = {"xapitoken": token, "xir": xir, "xil": xil, "xiu": xiu}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        body = r.json()
    return bool(body.get("ok", True)), body.get("msg")


async def run(args: argparse.Namespace) -> None:
    db = args.db_url or os.environ.get("DATABASE_URL")
    if not db:
        print("ERROR: falta DATABASE_URL en el entorno.", file=sys.stderr)
        sys.exit(1)

    xir = (args.xir or input("xir (id restaurante): ")).strip()
    xil = (args.xil or input("xil (id local): ")).strip()
    xiu = (args.xiu or input("xiu (id usuario): ")).strip()
    token = getpass.getpass("Pegá el xapitoken (no se mostrará): ").strip()
    if not (xir and xil and xiu and token):
        print("ERROR: faltan datos (xir/xil/xiu/xapitoken).", file=sys.stderr)
        sys.exit(1)

    if not args.skip_validate:
        print("Validando contra /shiftstatus…")
        try:
            ok, msg = await _validar(args.base_url, token, xir, xil, xiu)
        except Exception as e:
            print(f"ERROR validando (¿token/IDs incorrectos o base URL?): {e}", file=sys.stderr)
            sys.exit(1)
        if not ok:
            print(f"ERROR: Toteat rechazó las credenciales: {msg}", file=sys.stderr)
            sys.exit(1)
        print("  ✓ credenciales válidas.")

    config = {"xil": xil, "xiu": xiu, "base_url": args.base_url}
    conn = await asyncpg.connect(db)
    try:
        await conn.execute(
            """INSERT INTO public.integraciones
                   (tenant_id, proveedor, access_token, cuenta_id, config, activo, actualizado_en)
               VALUES ($1, 'toteat', $2, $3, $4::jsonb, TRUE, CURRENT_TIMESTAMP)
               ON CONFLICT (tenant_id, proveedor) DO UPDATE SET
                   access_token = EXCLUDED.access_token, cuenta_id = EXCLUDED.cuenta_id,
                   config = EXCLUDED.config, activo = TRUE, actualizado_en = CURRENT_TIMESTAMP""",
            args.tenant_id, token, xir, json.dumps(config),
        )
    finally:
        await conn.close()

    print(f"\n✓ Credenciales de Toteat guardadas para '{args.tenant_id}' (xir={xir}, xil={xil}).")
    print("  Siguiente:")
    print("   1) Backfill histórico (one-off; correr como script, NO por HTTP por el throttle):")
    print(f"      toteat.sincronizar(conn, '{args.tenant_id}', hoy-730, hoy)  # mock=False")
    print("   2) Sync diario: ya hay cron (/cron/sync_toteat.sh) — QUITAR '&mock=true' para datos reales.")


def main() -> None:
    p = argparse.ArgumentParser(description="Carga credenciales de Toteat de un tenant.")
    p.add_argument("--tenant-id", required=True, help="Tenant (ej. restaurante_toteat)")
    p.add_argument("--xir", default=None, help="Id restaurante (Toteat)")
    p.add_argument("--xil", default=None, help="Id local (Toteat)")
    p.add_argument("--xiu", default=None, help="Id usuario (Toteat)")
    p.add_argument("--base-url", default=BASE_DEFAULT, help=f"Base URL (default: {BASE_DEFAULT})")
    p.add_argument("--skip-validate", action="store_true", help="No validar contra /shiftstatus")
    p.add_argument("--db-url", default=None, help="DATABASE_URL (default: env)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
