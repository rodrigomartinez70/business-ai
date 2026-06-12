"""
P&L — vertical hotel. Solo aporta los hooks de ingresos y costo de ventas;
la estructura comparativa (Estado de Resultados) es horizontal en src.finanzas.pnl.
"""

from datetime import date

from src import config
from src.agents._common import to_float
from src.finanzas.pnl import (  # noqa: F401  (re-export de renderers)
    calcular_pnl_comparativo,
    renderizar_pnl_html,
    renderizar_pnl_markdown,
)
from src.finanzas.pnl_plantilla import calcular_desde_plantilla
from .tributario.ingresos import ingresos as ingresos_brutos


async def _costo_ventas(conn, ini: date, fin: date) -> float:
    """Costo de ventas del hotel: costo de frigobar + servicios (el hospedaje
    no tiene COGS directo; el personal va en gastos operativos)."""
    return to_float(await conn.fetchval("""
        SELECT COALESCE((SELECT SUM(costo_total) FROM consumos_frigobar WHERE fecha BETWEEN $1 AND $2), 0)
             + COALESCE((SELECT SUM(costo_total) FROM consumos_servicios WHERE fecha BETWEEN $1 AND $2), 0)
    """, ini, fin) or 0)


async def calcular_pnl(hasta: date) -> dict:
    pnl_cfg = (config.get_config() or {}).get("pnl") or {}
    if pnl_cfg.get("plantilla"):                 # override por empresa
        return await calcular_desde_plantilla(
            "hotel", pnl_cfg["plantilla"], pnl_cfg.get("constantes", {}), hasta)
    return await calcular_pnl_comparativo(hasta, ingresos_brutos, _costo_ventas)
