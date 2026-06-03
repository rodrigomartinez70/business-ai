"""
Agente Cierre — restaurante.

Resumen operativo del período: ventas (devengadas), cobrado (caja), gastos,
resultado, ticket promedio, nº de pedidos y propinas, con detalle por día.
"""

from datetime import date

from src import config
from src.agents._common import to_float


async def calcular_cierre_semanal(desde: date, hasta: date) -> dict:
    async with config.db_pool.acquire() as conn:
        ventas = to_float(await conn.fetchval("""
            SELECT COALESCE(SUM(d.total), 0)
            FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
            WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
        """, desde, hasta) or 0)
        cur = dict(await conn.fetchrow("""
            SELECT COUNT(*) AS n_pedidos, COALESCE(SUM(comensales), 0) AS comensales,
                   COALESCE(SUM(propina), 0) AS propinas
            FROM pedidos WHERE estado = 'pagado' AND fecha BETWEEN $1 AND $2
        """, desde, hasta))
        cobrado = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE estado = 'pagado' AND fecha BETWEEN $1 AND $2",
            desde, hasta) or 0)
        gastos = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha BETWEEN $1 AND $2",
            desde, hasta) or 0)
        por_dia = await conn.fetch("""
            SELECT p.fecha, COALESCE(SUM(d.total), 0) AS ventas, COUNT(DISTINCT p.id) AS n_pedidos
            FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
            WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
            GROUP BY p.fecha ORDER BY p.fecha
        """, desde, hasta)

    n = int(cur["n_pedidos"])
    resultado = round(ventas - gastos, 2)
    return {
        "periodo": {"inicio": str(desde), "fin": str(hasta)},
        "totales": {
            "ventas": ventas,
            "cobrado": cobrado,
            "gastos": gastos,
            "resultado": resultado,
            "resultado_estado": "positivo" if resultado >= 0 else "negativo",
            "n_pedidos": n,
            "ticket_promedio": round(ventas / n) if n else 0,
            "comensales": int(cur["comensales"]),
            "propinas": to_float(cur["propinas"]),
        },
        "por_dia": [{"fecha": str(r["fecha"]), "ventas": to_float(r["ventas"]),
                     "n_pedidos": int(r["n_pedidos"])} for r in por_dia],
    }
