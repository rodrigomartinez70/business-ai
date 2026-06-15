"""
Categorización de proveedores del RCV de compras.

Mapea cada proveedor a una categoría de gasto OPEX (categorias_gasto) y permite
marcarlo como `es_comida` (insumo → COGS) para excluirlo del control de gastos.
Las reglas se guardan por empresa (categorias_proveedor) y se re-aplican a las
compras (documentos_tributarios) en cada carga del RCV.
"""

from __future__ import annotations

import logging

from .. import config
from ..admin.tenants import _TENANT_RE

logger = logging.getLogger(__name__)


class CatError(Exception):
    """Error de validación (→ 400)."""


async def aplicar(conn, tenant_id: str) -> int:
    """Escribe categoria_gasto en cada compra según la regla de su proveedor.
    Asume search_path ya seteado al tenant. Devuelve filas actualizadas."""
    r = await conn.execute("""
        UPDATE documentos_tributarios d
           SET categoria_gasto = cp.categoria, updated_at = now()
          FROM categorias_proveedor cp
         WHERE d.clase = 'compra' AND d.proveedor = cp.proveedor
           AND cp.categoria IS NOT NULL
           AND d.categoria_gasto IS DISTINCT FROM cp.categoria
    """)
    return int(r.rsplit(" ", 1)[-1]) if r.startswith("UPDATE") else 0


async def listar_proveedores(tenant_id: str) -> list[dict]:
    """Proveedores de compras del RCV con total/n y su regla actual (si existe)."""
    async with config.raw_pool.acquire() as conn:
        await conn.execute(f'SET search_path = "{tenant_id}"')
        rows = await conn.fetch("""
            SELECT d.proveedor,
                   COUNT(*) AS n, SUM(d.monto_neto) AS total,
                   cp.categoria, COALESCE(cp.es_comida, FALSE) AS es_comida
            FROM documentos_tributarios d
            LEFT JOIN categorias_proveedor cp ON cp.proveedor = d.proveedor
            WHERE d.clase = 'compra'
            GROUP BY d.proveedor, cp.categoria, cp.es_comida
            ORDER BY total DESC
        """)
    return [dict(r) for r in rows]


async def listar_categorias(tenant_id: str) -> list[str]:
    async with config.raw_pool.acquire() as conn:
        await conn.execute(f'SET search_path = "{tenant_id}"')
        rows = await conn.fetch("SELECT nombre FROM categorias_gasto ORDER BY nombre")
    return [r["nombre"] for r in rows]


async def guardar_regla(tenant_id: str, proveedor: str, categoria: str, es_comida: bool) -> int:
    """Upsert de la regla del proveedor + re-aplica a sus compras. Devuelve filas tocadas."""
    if not _TENANT_RE.match(tenant_id):
        raise CatError("ID de empresa inválido.")
    proveedor = (proveedor or "").strip()
    if not proveedor:
        raise CatError("Proveedor vacío.")
    categoria = (categoria or "").strip() or None
    async with config.raw_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(f'SET LOCAL search_path = "{tenant_id}"')
            await conn.execute("""
                INSERT INTO categorias_proveedor (proveedor, categoria, es_comida)
                VALUES ($1, $2, $3)
                ON CONFLICT (proveedor) DO UPDATE
                    SET categoria = EXCLUDED.categoria, es_comida = EXCLUDED.es_comida
            """, proveedor, categoria, es_comida)
            tocadas = await aplicar(conn, tenant_id)
    logger.info(f"[cat] regla {proveedor} → {categoria} (comida={es_comida}) en {tenant_id}")
    return tocadas
