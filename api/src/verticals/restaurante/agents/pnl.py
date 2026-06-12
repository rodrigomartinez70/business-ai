"""
P&L — vertical restaurante. Solo aporta los hooks de ingresos y costo de ventas
(food cost); la estructura comparativa es horizontal en src.finanzas.pnl.
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
    """Food cost: costo de los productos vendidos (pedidos pagados)."""
    return to_float(await conn.fetchval("""
        SELECT COALESCE(SUM(d.costo_total), 0)
        FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
        WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
    """, ini, fin) or 0)


async def calcular_pnl(hasta: date) -> dict:
    pnl_cfg = (config.get_config() or {}).get("pnl") or {}
    if pnl_cfg.get("plantilla"):                 # override por empresa
        return await calcular_desde_plantilla(
            "restaurante", pnl_cfg["plantilla"], pnl_cfg.get("constantes", {}), hasta)
    return await calcular_pnl_comparativo(hasta, ingresos_brutos, _costo_ventas)
