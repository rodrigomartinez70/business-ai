"""Ingreso afecto del vertical restaurante: ventas de pedidos pagados."""

from datetime import date

from src.agents._common import to_float


async def ingresos(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval("""
        SELECT COALESCE(SUM(d.total), 0)
        FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
        WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
    """, ini, fin) or 0)
