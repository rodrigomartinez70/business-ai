"""Métricas del vertical hotel (hospedaje devengado + consumos)."""

from datetime import date

from src.metricas.registry import metrica
from src.agents._common import to_float

_V = "hotel"


@metrica("hospedaje", unidad="moneda", label="Hospedaje (devengado)", vertical=_V)
async def hospedaje(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        """SELECT COALESCE(SUM(total_hospedaje),0) FROM reservas
            WHERE estado='checkout' AND fecha_salida BETWEEN $1 AND $2""", ini, fin) or 0)


@metrica("noches", unidad="numero", label="Noches vendidas", vertical=_V)
async def noches(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        """SELECT COALESCE(SUM(noches),0) FROM reservas
            WHERE estado='checkout' AND fecha_salida BETWEEN $1 AND $2""", ini, fin) or 0)


@metrica("consumos", unidad="moneda", label="Consumos (frigobar + servicios)", vertical=_V)
async def consumos(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        """SELECT COALESCE((SELECT SUM(total) FROM consumos_frigobar WHERE fecha BETWEEN $1 AND $2),0)
                + COALESCE((SELECT SUM(total) FROM consumos_servicios WHERE fecha BETWEEN $1 AND $2),0)""",
        ini, fin) or 0)


@metrica("ingresos", unidad="moneda", label="Ingresos", vertical=_V)
async def ingresos(conn, ini: date, fin: date) -> float:
    return await hospedaje(conn, ini, fin) + await consumos(conn, ini, fin)
