"""Métricas del vertical restaurante (pedidos pagados)."""

from datetime import date

from src.metricas.registry import metrica
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
