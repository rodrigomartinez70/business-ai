"""Métricas horizontales — sobre las tablas comunes (pagos, gastos)."""

from datetime import date

from .registry import metrica
from ..agents._common import to_float


@metrica("cobros", unidad="moneda", label="Cobros (pagos recibidos)")
async def cobros(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        "SELECT COALESCE(SUM(monto),0) FROM pagos WHERE fecha BETWEEN $1 AND $2", ini, fin) or 0)


@metrica("gastos_total", unidad="moneda", label="Gastos totales")
async def gastos_total(conn, ini: date, fin: date) -> float:
    return to_float(await conn.fetchval(
        "SELECT COALESCE(SUM(monto),0) FROM gastos WHERE fecha BETWEEN $1 AND $2", ini, fin) or 0)
