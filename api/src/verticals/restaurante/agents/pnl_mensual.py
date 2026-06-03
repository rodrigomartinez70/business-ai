"""
Agente P&L mensual — restaurante.

Ingresos (ventas pagadas) − costo de productos (food cost) − gastos operativos
= resultado. Compara contra el mes anterior y el mismo mes del año anterior.
"""

from datetime import date, timedelta

from src import config
from src.agents._common import to_float, var_pct

_MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio",
          "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _rango_mes(anchor: date) -> tuple[date, date]:
    ini = date(anchor.year, anchor.month, 1)
    fin = date(anchor.year, 12, 31) if anchor.month == 12 else \
        date(anchor.year, anchor.month + 1, 1) - timedelta(days=1)
    return ini, fin


async def _mes(conn, ini: date, fin: date) -> dict:
    row = dict(await conn.fetchrow("""
        SELECT COALESCE(SUM(d.total), 0) AS ingresos,
               COALESCE(SUM(d.costo_total), 0) AS costo,
               COUNT(DISTINCT p.id) AS n
        FROM pedidos p JOIN detalle_pedido d ON d.pedido_id = p.id
        WHERE p.estado = 'pagado' AND p.fecha BETWEEN $1 AND $2
    """, ini, fin))
    gastos = to_float(await conn.fetchval(
        "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha BETWEEN $1 AND $2", ini, fin) or 0)
    ingresos = to_float(row["ingresos"])
    costo    = to_float(row["costo"])
    return {
        "ingresos": ingresos, "costo": costo, "gastos": gastos,
        "resultado": round(ingresos - costo - gastos, 2), "n": int(row["n"]),
    }


async def calcular_pnl(hasta: date) -> dict:
    inicio_mes, _ = _rango_mes(hasta)
    prev_anchor = inicio_mes - timedelta(days=1)
    prev_ini, prev_fin = _rango_mes(prev_anchor)
    ya_ini = date(hasta.year - 1, hasta.month, 1)
    _, ya_fin_full = _rango_mes(ya_ini)

    async with config.db_pool.acquire() as conn:
        actual = await _mes(conn, inicio_mes, hasta)
        prev   = await _mes(conn, prev_ini, prev_fin)
        ya     = await _mes(conn, ya_ini, ya_fin_full)

    ingresos = actual["ingresos"]
    margen_pct = round(actual["resultado"] / ingresos * 100, 1) if ingresos else 0
    food_cost_pct = round(actual["costo"] / ingresos * 100, 1) if ingresos else 0

    return {
        "periodo": {"inicio": str(inicio_mes), "fin": str(hasta)},
        "mes_nombre": _MESES[hasta.month],
        "parcial": hasta != _rango_mes(hasta)[1],
        "actual": {
            "ingresos": ingresos,
            "costo_productos": actual["costo"],
            "gastos_operativos": actual["gastos"],
            "resultado": actual["resultado"],
            "margen_pct": margen_pct,
        },
        "comparativas": {
            "ingresos":  {"vs_mes_anterior": var_pct(ingresos, prev["ingresos"])},
            "resultado": {"vs_mes_anterior": var_pct(actual["resultado"], prev["resultado"]),
                          "vs_año_anterior": var_pct(actual["resultado"], ya["resultado"])},
        },
        "metricas": {
            "ticket_promedio": round(ingresos / actual["n"]) if actual["n"] else 0,
            "n_pedidos": actual["n"],
            "food_cost_pct": food_cost_pct,
        },
    }
