"""Métricas del vertical restaurante (pedidos pagados)."""

from datetime import date

from src.metricas.registry import metrica, tabla
from src.agents._common import to_float

_V = "restaurante"


@metrica("ventas", unidad="moneda", label="Ventas (pedidos pagados)", vertical=_V)
async def ventas(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        """SELECT COALESCE(SUM(d.total),0) FROM pedidos p JOIN detalle_pedido d ON d.pedido_id=p.id
            WHERE p.estado='pagado' AND p.fecha BETWEEN $1 AND $2""", ini, fin) or 0)


@metrica("costo_ventas", unidad="moneda", label="Costo de ventas (food cost)", vertical=_V)
async def costo_ventas(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        """SELECT COALESCE(SUM(d.costo_total),0) FROM pedidos p JOIN detalle_pedido d ON d.pedido_id=p.id
            WHERE p.estado='pagado' AND p.fecha BETWEEN $1 AND $2""", ini, fin) or 0)


@metrica("n_pedidos", unidad="numero", label="N° de pedidos pagados", vertical=_V)
async def n_pedidos(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        "SELECT COUNT(*) FROM pedidos WHERE estado='pagado' AND fecha BETWEEN $1 AND $2",
        ini, fin) or 0)


@metrica("propinas", unidad="moneda", label="Propinas", vertical=_V)
async def propinas(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        "SELECT COALESCE(SUM(propina),0) FROM pedidos WHERE estado='pagado' AND fecha BETWEEN $1 AND $2",
        ini, fin) or 0)


@metrica("ingresos", unidad="moneda", label="Ingresos", vertical=_V)
async def ingresos(conn, ini: date, fin: date) -> float:
    return await ventas(conn, ini, fin)


# ── Fuentes de tabla (desglose de Ventas) ───────────────────────────────

@tabla("ventas_por_canal", vertical=_V,
       columnas=[("canal", "Canal", "texto"), ("ventas", "Ventas", "moneda"),
                 ("mix", "Mix", "pct"), ("ticket", "Ticket", "moneda")])
async def ventas_por_canal(conn, ini: date, fin: date) -> list[dict]:
    rows = await conn.fetch(
        """SELECT COALESCE(cv.nombre,'(sin canal)') AS canal,
                  COALESCE(SUM(d.total),0) AS ventas, COUNT(DISTINCT p.id) AS n
             FROM pedidos p LEFT JOIN canales_venta cv ON cv.id = p.canal_id
             JOIN detalle_pedido d ON d.pedido_id = p.id
            WHERE p.estado='pagado' AND p.fecha BETWEEN $1 AND $2
            GROUP BY cv.nombre ORDER BY ventas DESC""", ini, fin)
    total = sum(to_float(r["ventas"]) for r in rows) or 1.0
    return [{"canal": r["canal"], "ventas": to_float(r["ventas"]),
             "mix": round(to_float(r["ventas"]) / total * 100, 1),
             "ticket": round(to_float(r["ventas"]) / r["n"], 0) if r["n"] else 0}
            for r in rows]


@tabla("top_productos", vertical=_V,
       columnas=[("producto", "Producto", "texto"), ("cantidad", "Cant.", "numero"),
                 ("ventas", "Ventas", "moneda")])
async def top_productos(conn, ini: date, fin: date) -> list[dict]:
    rows = await conn.fetch(
        """SELECT pr.nombre AS producto, SUM(d.cantidad) AS cantidad, SUM(d.total) AS ventas
             FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
             JOIN productos pr ON pr.id = d.producto_id
            WHERE p.estado='pagado' AND p.fecha BETWEEN $1 AND $2
            GROUP BY pr.nombre ORDER BY ventas DESC LIMIT 5""", ini, fin)
    return [{"producto": r["producto"], "cantidad": int(r["cantidad"] or 0),
             "ventas": to_float(r["ventas"])} for r in rows]
