"""
Agente Cuentas por Cobrar (horizontal).

En negocios POS el cobro suele ser inmediato, así que la cartera por cobrar son
las ventas ya devengadas pero aún no cobradas:
  - hotel:       reservas con estancia ya consumida (fecha_salida ≤ corte) cuyo
                 total_hospedaje supera lo pagado de esa reserva.
  - restaurante: pedidos con consumo cerrado pero estado distinto de pagado/anulado.

Entrega cartera total, aging por antigüedad y DSO (días de venta pendientes de
cobro, sobre la venta diaria promedio de los últimos 90 días). Sin LLM — SQL puro.
"""

import logging
from datetime import date, timedelta

import asyncpg

from src import config
from src.tenant import get_tenant_or_none
from src.agents._common import to_float, fetchval_opt

logger = logging.getLogger(__name__)

_MAX_LISTA = 10
_COBRADOS = ("cobrado", "cobrada", "pagado", "pagada", "anulado", "anulada")


async def _cartera_documentos(conn, hasta: date) -> list[dict]:
    """CxC de una empresa sin POS: facturas/boletas emitidas del RCV (clase='venta')
    aún no cobradas. El SII da el documento; el estado de cobro real exige conciliar
    con el banco o el ERP."""
    try:
        rows = await conn.fetch(
            "SELECT fecha, proveedor AS cliente, monto_total AS total "
            "FROM documentos_tributarios "
            "WHERE clase = 'venta' AND fecha <= $1 "
            "AND LOWER(COALESCE(estado, '')) <> ALL($2::text[])", hasta, list(_COBRADOS))
    except asyncpg.UndefinedColumnError:
        return []
    return [{"fecha": r["fecha"], "cliente": r["cliente"] or "—",
             "monto": round(to_float(r["total"]), 2)}
            for r in rows if to_float(r["total"]) > 1]


async def _ventas_doc_90(conn, desde: date, hasta: date) -> float:
    """Ventas emitidas (RCV) en la ventana, para el DSO de una empresa sin POS."""
    try:
        v = await conn.fetchval(
            "SELECT COALESCE(SUM(monto_total), 0) FROM documentos_tributarios "
            "WHERE clase = 'venta' AND fecha BETWEEN $1 AND $2", desde, hasta)
    except asyncpg.UndefinedColumnError:
        return 0.0
    return to_float(v or 0)


async def _cartera_hotel(conn, hasta: date) -> list[dict]:
    rows = await conn.fetch(
        """SELECT r.id, r.fecha_salida AS fecha, h.nombre AS cliente,
                  r.total_hospedaje AS total,
                  COALESCE((SELECT SUM(p.monto) FROM pagos p WHERE p.reserva_id = r.id), 0) AS pagado
             FROM reservas r JOIN huespedes h ON h.id = r.huesped_id
            WHERE r.fecha_salida <= $1
              AND LOWER(COALESCE(r.estado, '')) NOT IN ('anulada', 'cancelada', 'no_show')""",
        hasta)
    out = []
    for r in rows:
        saldo = to_float(r["total"]) - to_float(r["pagado"])
        if saldo > 1:
            out.append({"fecha": r["fecha"], "cliente": r["cliente"] or "—",
                        "monto": round(saldo, 2)})
    return out


async def _cartera_restaurante(conn, hasta: date) -> list[dict]:
    rows = await conn.fetch(
        """SELECT p.id, p.fecha,
                  COALESCE(SUM(d.total), 0) AS total
             FROM pedidos p LEFT JOIN detalle_pedido d ON d.pedido_id = p.id
            WHERE p.fecha <= $1
              AND LOWER(COALESCE(p.estado, '')) NOT IN ('pagado', 'pagada', 'anulado', 'anulada')
            GROUP BY p.id, p.fecha""",
        hasta)
    return [{"fecha": r["fecha"], "cliente": f"Pedido #{r['id']}",
             "monto": round(to_float(r["total"]), 2)}
            for r in rows if to_float(r["total"]) > 1]


async def calcular_cuentas_por_cobrar(hasta: date) -> dict:
    vertical = (get_tenant_or_none().vertical if get_tenant_or_none() else "hotel")
    desde_90 = hasta - timedelta(days=89)

    async with config.db_pool.acquire() as conn:
        if vertical == "restaurante":
            cartera = await _cartera_restaurante(conn, hasta)
        elif vertical == "hotel":
            cartera = await _cartera_hotel(conn, hasta)
        else:
            cartera = await _cartera_documentos(conn, hasta)   # sin POS → facturas emitidas (RCV)
        if vertical in ("restaurante", "hotel"):
            ventas_90 = to_float(await fetchval_opt(conn,
                "SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE fecha BETWEEN $1 AND $2",
                desde_90, hasta) or 0)
        else:
            ventas_90 = await _ventas_doc_90(conn, desde_90, hasta)

    buckets = {"d0_30": 0.0, "d31_60": 0.0, "d60_mas": 0.0}
    items = []
    total = 0.0
    for c in cartera:
        monto = c["monto"]
        total += monto
        dias = (hasta - c["fecha"]).days
        if dias <= 30:
            buckets["d0_30"] += monto
        elif dias <= 60:
            buckets["d31_60"] += monto
        else:
            buckets["d60_mas"] += monto
        items.append({"fecha": str(c["fecha"]), "cliente": c["cliente"],
                      "monto": monto, "dias": dias})

    items.sort(key=lambda x: -x["dias"])
    venta_diaria = ventas_90 / 90 if ventas_90 else 0.0
    dso = round(total / venta_diaria, 1) if venta_diaria else None

    return {
        "corte": str(hasta),
        "vertical": vertical,
        "total_por_cobrar": round(total, 2),
        "dso": dso,
        "vencido_60_mas": round(buckets["d60_mas"], 2),
        "aging": {k: round(v, 2) for k, v in buckets.items()},
        "documentos": len(items),
        "detalle": items[:_MAX_LISTA],
    }


def renderizar_cxc_markdown(data: dict) -> str:
    a = data["aging"]
    out = ["# Cuentas por Cobrar",
           f"\nCorte: {data['corte']}",
           f"- Total por cobrar: ${data['total_por_cobrar']:,.0f} ({data['documentos']} docs)",
           f"- DSO: {data['dso'] if data['dso'] is not None else 's/d'} días",
           "\n## Aging",
           f"- 0–30 días: ${a['d0_30']:,.0f}",
           f"- 31–60 días: ${a['d31_60']:,.0f}",
           f"- +60 días: ${a['d60_mas']:,.0f}"]
    if data["detalle"]:
        out.append("\n## Cartera (más antigua primero)")
        for d in data["detalle"]:
            out.append(f"- {d['fecha']} · {d['cliente']} · ${d['monto']:,.0f} · {d['dias']}d")
    elif data["total_por_cobrar"] == 0:
        out.append("\nSin cartera pendiente: el cobro es al contado en este período.")
    return "\n".join(out)
