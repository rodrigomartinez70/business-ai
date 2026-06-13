"""
Agente Cuentas por Pagar (horizontal).

Fuente: documentos_tributarios (facturas de compra recibidas). Una factura cuenta
como obligación pendiente mientras su estado no sea pagado/anulado. El modelo no
guarda fecha de vencimiento, así que se estima como fecha + PLAZO_DIAS (plazo
comercial típico en Chile, configurable). Entrega aging, próximos vencimientos,
vencidas y ranking por proveedor — la base para priorizar pagos en Tesorería.
Sin LLM — SQL puro.
"""

import logging
from datetime import date, timedelta

import asyncpg

from src import config
from src.agents._common import to_float

logger = logging.getLogger(__name__)

PLAZO_DIAS = 30                       # plazo comercial estimado si no hay vencimiento real
_PAGADOS   = ("pagado", "pagada", "anulado", "anulada", "rechazado")
_MAX_LISTA = 10


def _monto(d) -> float:
    total = to_float(d["monto_total"]) if d["monto_total"] is not None else 0.0
    if total <= 0:                    # fallback: neto + iva
        total = to_float(d["monto_neto"]) + to_float(d["monto_iva"] or 0)
    return total


async def calcular_cuentas_por_pagar(hasta: date, plazo_dias: int = PLAZO_DIAS) -> dict:
    """CxP abiertas al corte `hasta`, con vencimiento estimado = fecha + plazo_dias."""
    # Solo facturas de COMPRA (clase='compra'); las ventas del RCV no son obligaciones
    # a pagar. Defensivo: si el schema no tiene `clase` (pre-012), solo había compras.
    _sql = ("SELECT fecha, proveedor, numero_documento, monto_neto, monto_iva, "
            "monto_total, estado FROM documentos_tributarios "
            "WHERE LOWER(COALESCE(estado, '')) <> ALL($1::text[]) AND fecha <= $2 {clase} "
            "ORDER BY fecha")
    async with config.db_pool.acquire() as conn:
        try:
            docs = await conn.fetch(_sql.format(clase="AND clase = 'compra'"), list(_PAGADOS), hasta)
        except asyncpg.UndefinedColumnError:
            docs = await conn.fetch(_sql.format(clase=""), list(_PAGADOS), hasta)

    buckets = {"por_vencer": 0.0, "d1_30": 0.0, "d31_60": 0.0, "d60_mas": 0.0}
    por_proveedor: dict[str, float] = {}
    vencidas, proximas = [], []
    total = 0.0

    for d in docs:
        monto = _monto(d)
        if monto <= 0:
            continue
        total += monto
        vence = d["fecha"] + timedelta(days=plazo_dias)
        atraso = (hasta - vence).days          # >0 = vencida hace `atraso` días
        prov = d["proveedor"] or "—"
        por_proveedor[prov] = por_proveedor.get(prov, 0.0) + monto

        if atraso <= 0:
            buckets["por_vencer"] += monto
        elif atraso <= 30:
            buckets["d1_30"] += monto
        elif atraso <= 60:
            buckets["d31_60"] += monto
        else:
            buckets["d60_mas"] += monto

        item = {"fecha": str(d["fecha"]), "vence": str(vence), "proveedor": prov,
                "documento": d["numero_documento"], "monto": round(monto, 2),
                "dias": abs(atraso)}
        (vencidas if atraso > 0 else proximas).append(item)

    vencidas.sort(key=lambda x: -x["dias"])    # más atrasadas primero
    proximas.sort(key=lambda x: x["vence"])    # más próximas a vencer primero
    ranking = sorted(({"proveedor": p, "monto": round(m, 2)}
                      for p, m in por_proveedor.items()),
                     key=lambda x: -x["monto"])

    return {
        "corte": str(hasta),
        "plazo_dias": plazo_dias,
        "total_por_pagar": round(total, 2),
        "vencido": round(buckets["d1_30"] + buckets["d31_60"] + buckets["d60_mas"], 2),
        "aging": {k: round(v, 2) for k, v in buckets.items()},
        "documentos": len(vencidas) + len(proximas),
        "vencidas": vencidas[:_MAX_LISTA],
        "vencidas_total": len(vencidas),
        "proximos_vencimientos": proximas[:_MAX_LISTA],
        "por_proveedor": ranking[:_MAX_LISTA],
    }


def renderizar_cxp_markdown(data: dict) -> str:
    a = data["aging"]
    out = ["# Cuentas por Pagar",
           f"\nCorte: {data['corte']} · vencimiento estimado a {data['plazo_dias']} días",
           f"- Total por pagar: ${data['total_por_pagar']:,.0f} ({data['documentos']} docs)",
           f"- Vencido: ${data['vencido']:,.0f}",
           "\n## Aging",
           f"- Por vencer: ${a['por_vencer']:,.0f}",
           f"- 1–30 días: ${a['d1_30']:,.0f}",
           f"- 31–60 días: ${a['d31_60']:,.0f}",
           f"- +60 días: ${a['d60_mas']:,.0f}"]
    if data["vencidas"]:
        out.append(f"\n## Vencidas ({data['vencidas_total']})")
        for v in data["vencidas"]:
            out.append(f"- {v['vence']} · {v['proveedor']} · ${v['monto']:,.0f} "
                       f"· {v['dias']}d de atraso")
    if data["proximos_vencimientos"]:
        out.append("\n## Próximos vencimientos")
        for v in data["proximos_vencimientos"]:
            out.append(f"- {v['vence']} · {v['proveedor']} · ${v['monto']:,.0f}")
    return "\n".join(out)
