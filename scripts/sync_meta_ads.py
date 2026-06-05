#!/usr/bin/env python3
"""
Sincroniza insights de Meta Ads → Postgres para un tenant.

Uso:
  # Modo mock (sin token; genera datos de muestra):
  python scripts/sync_meta_ads.py --tenant-id inmobiliaria --dias 60 --mock

  # Modo real (lee credenciales de public.integraciones, proveedor='meta'):
  python scripts/sync_meta_ads.py --tenant-id inmobiliaria --dias 30

  # Rango explícito:
  python scripts/sync_meta_ads.py --tenant-id inmobiliaria --desde 2026-04-01 --hasta 2026-04-30

Requiere DATABASE_URL (o INGEST_DATABASE_URL) en el entorno.
"""

import argparse
import asyncio
import os
import sys
from datetime import date, datetime, timedelta

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from src.integraciones import meta_ads  # noqa: E402

DATABASE_URL = os.environ.get("INGEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _parse_fecha(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


async def run(args: argparse.Namespace) -> None:
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL no configurado", file=sys.stderr)
        sys.exit(1)

    if args.desde and args.hasta:
        desde, hasta = _parse_fecha(args.desde), _parse_fecha(args.hasta)
    else:
        hasta = date.today()
        desde = hasta - timedelta(days=args.dias)

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute(f'SET search_path = "{args.tenant_id}", public')
        res = await meta_ads.sincronizar(conn, args.tenant_id, desde, hasta, mock=args.mock)
    finally:
        await conn.close()

    print(f"✓ Meta Ads [{res['modo']}] tenant={res['tenant']} "
          f"{res['desde']}→{res['hasta']}: {res['campanas']} campañas, "
          f"{res['insights']} insights.")


def main() -> None:
    p = argparse.ArgumentParser(description="Sincroniza insights de Meta Ads a Postgres.")
    p.add_argument("--tenant-id", required=True, help="Schema del tenant (ej. inmobiliaria)")
    p.add_argument("--dias", type=int, default=30, help="Días hacia atrás (si no se da rango)")
    p.add_argument("--desde", default=None, help="Fecha inicio YYYY-MM-DD")
    p.add_argument("--hasta", default=None, help="Fecha fin YYYY-MM-DD")
    p.add_argument("--mock", action="store_true", help="Genera datos de muestra sin llamar a la API")
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
