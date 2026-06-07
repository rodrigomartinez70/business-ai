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

# URLs candidatas de Toteat (prod/dev, nuevas y legacy) para diagnosticar el ambiente.
BASES_CANDIDATAS = [
    "https://api.toteat.com/mw/or/1.0/",
    "https://apidev.toteat.com/mw/or/1.0/",
    "https://toteatglobal.appspot.com/mw/or/1.0/",
    "https://toteatdev.appspot.com/mw/or/1.0/",
    "https://www.toteatdev.appspot.com/mw/or/1.0/",
]


async def _validar(base: str, token: str, xir: str, xil: str, xiu: str, endpoint: str = "shiftstatus"):
    url = base.rstrip("/") + "/" + endpoint
    params = {"xapitoken": token, "xir": xir, "xil": xil, "xiu": xiu}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=params)
    info = f"HTTP {r.status_code}"
    try:
        body = r.json()
    except Exception:
        return False, f"{info} (respuesta no-JSON): {r.text[:400]}"
    return bool(body.get("ok", False)), f"{info} · body={json.dumps(body, ensure_ascii=False)[:600]}"


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

    if args.probe:
        print(f"\nProbe (no guarda nada). Credenciales: xir={xir} xil={xil} xiu={xiu} "
              f"token_len={len(token)}")
        print("— Endpoints en prod (api.toteat.com):")
        for ep in ("products", "shiftstatus", "tables"):
            try:
                ok, info = await _validar(args.base_url, token, xir, xil, xiu, endpoint=ep)
                print(f"  {'✅' if ok else '  '} /{ep}\n        {info}")
            except Exception as e:
                print(f"     /{ep}\n        ERROR: {e}")
        print("— /shiftstatus en otras URLs:")
        for base in BASES_CANDIDATAS[1:4]:
            try:
                ok, info = await _validar(base, token, xir, xil, xiu)
                print(f"  {'✅' if ok else '  '} {base} → {info}")
            except Exception as e:
                print(f"     {base} → ERROR: {e}")
        print("\nSi NINGÚN endpoint da ok=true → el token está mal/vencido (pedir uno nuevo a Toteat).")
        return

    if not args.skip_validate:
        print(f"Validando contra /shiftstatus ({args.base_url})…")
        try:
            ok, info = await _validar(args.base_url, token, xir, xil, xiu)
        except Exception as e:
            print(f"ERROR validando (¿base URL/red?): {e}", file=sys.stderr)
            sys.exit(1)
        print(f"  respuesta: {info}")
        if not ok:
            print("ERROR: Toteat rechazó las credenciales. Revisá xiu (middleware id), "
                  "xir/xil y el Environment (base URL). No se guardó nada.", file=sys.stderr)
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
    p.add_argument("--probe", action="store_true",
                   help="Diagnóstico: prueba el token contra todas las URLs de Toteat y no guarda")
    p.add_argument("--db-url", default=None, help="DATABASE_URL (default: env)")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
