"""Ingreso afecto del vertical hotel: hospedaje (devengado) + frigobar + servicios."""

from datetime import date

from src.agents._common import to_float


async def ingresos(conn, ini: date, fin: date) -> float:
    """Agregados separados para evitar el fan-out del JOIN uno-a-muchos."""
    row = await conn.fetchrow("""
        SELECT
            (SELECT COALESCE(SUM(total_hospedaje), 0) FROM reservas
              WHERE fecha_salida BETWEEN $1 AND $2 AND estado = 'checkout')
          + (SELECT COALESCE(SUM(total), 0) FROM consumos_frigobar WHERE fecha BETWEEN $1 AND $2)
          + (SELECT COALESCE(SUM(total), 0) FROM consumos_servicios WHERE fecha BETWEEN $1 AND $2) AS total
    """, ini, fin)
    return to_float(row["total"])
