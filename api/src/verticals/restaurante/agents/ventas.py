"""
Agente de Ventas — restaurante.

Ventas (pedidos pagados), ticket promedio, margen bruto (food cost), mix por
canal (salón/delivery/apps) y por día, y top productos.
"""

from datetime import date, timedelta

from src import config
from src.agents._common import to_float


async def calcular_ventas(desde: date, hasta: date) -> dict:
    dias        = (hasta - desde).days + 1
    prev_fin    = desde - timedelta(days=1)
    prev_inicio = prev_fin - timedelta(days=dias - 1)

    async with config.db_pool.acquire() as conn:
        cur = dict(await conn.fetchrow("""
            SELECT COALESCE(SUM(d.total), 0)        AS ventas,
                   COALESCE(SUM(d.costo_total), 0)  AS costo,
                   COUNT(DISTINCT p.id)             AS n_pedidos,
                   COALESCE(SUM(p.comensales), 0)   AS comensales
            FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
            WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
        """, desde, hasta))

        prev = to_float(await conn.fetchval("""
            SELECT COALESCE(SUM(d.total), 0)
            FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
            WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
        """, prev_inicio, prev_fin) or 0)

        propinas = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(propina), 0) FROM pedidos "
            "WHERE estado = 'pagado' AND fecha BETWEEN $1 AND $2", desde, hasta) or 0)

        por_canal = await conn.fetch("""
            SELECT c.nombre AS canal, COALESCE(SUM(d.total), 0) AS ventas,
                   COUNT(DISTINCT p.id) AS n_pedidos
            FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
            LEFT JOIN canales_venta c ON c.id = p.canal_id
            WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
            GROUP BY c.nombre ORDER BY 2 DESC
        """, desde, hasta)

        por_dia = await conn.fetch("""
            SELECT p.fecha, COALESCE(SUM(d.total), 0) AS ventas, COUNT(DISTINCT p.id) AS n_pedidos
            FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
            WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
            GROUP BY p.fecha ORDER BY p.fecha
        """, desde, hasta)

        top = await conn.fetch("""
            SELECT pr.nombre AS producto, SUM(d.cantidad) AS cantidad,
                   SUM(d.total) AS ventas, SUM(d.margen) AS margen
            FROM detalle_pedido d JOIN pedidos p ON p.id = d.pedido_id
            LEFT JOIN productos pr ON pr.id = d.producto_id
            WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
            GROUP BY pr.nombre ORDER BY ventas DESC LIMIT 5
        """, desde, hasta)

    ventas = to_float(cur["ventas"])
    costo  = to_float(cur["costo"])
    n      = int(cur["n_pedidos"])
    margen = ventas - costo
    ticket = round(ventas / n) if n else 0
    variacion = round((ventas - prev) / prev * 100, 1) if prev > 0 else None
    total_canal = sum(to_float(r["ventas"]) for r in por_canal) or 1

    return {
        "periodo": {"inicio": str(desde), "fin": str(hasta), "dias": dias,
                    "prev_inicio": str(prev_inicio), "prev_fin": str(prev_fin)},
        "resumen": {
            "ventas_total": ventas, "ventas_anterior": prev, "variacion_pct": variacion,
            "n_pedidos": n, "ticket_promedio": ticket, "comensales": int(cur["comensales"]),
            "costo_productos": costo, "margen_bruto": margen,
            "margen_pct": round(margen / ventas * 100, 1) if ventas else 0,
            "propinas": propinas,
        },
        "por_canal": [{
            "canal": r["canal"] or "Sin canal", "ventas": to_float(r["ventas"]),
            "mix_pct": round(to_float(r["ventas"]) / total_canal * 100, 1),
            "n_pedidos": int(r["n_pedidos"]),
            "ticket": round(to_float(r["ventas"]) / int(r["n_pedidos"])) if int(r["n_pedidos"]) else 0,
        } for r in por_canal],
        "por_dia": [{"fecha": str(r["fecha"]), "ventas": to_float(r["ventas"]),
                     "n_pedidos": int(r["n_pedidos"])} for r in por_dia],
        "top_productos": [{"producto": r["producto"] or "—", "cantidad": int(r["cantidad"]),
                           "ventas": to_float(r["ventas"]), "margen": to_float(r["margen"])} for r in top],
    }
