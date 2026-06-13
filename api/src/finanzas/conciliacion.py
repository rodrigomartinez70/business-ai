"""
Agente Conciliación bancaria.

Cruza los movimientos de la cartola del banco (tabla movimientos_bancarios,
cargada por el usuario vía CSV — el agente NO se conecta al banco) contra los
registros de los libros: pagos (ingresos) y gastos (egresos). Reporta el %
conciliado y las excepciones a revisar.

Regla de match: mismo monto (±$1) y fecha dentro de ±3 días.
  - Abono (monto > 0)  → calza con pagos (ingresos).
  - Cargo (monto < 0)  → calza con gastos (egresos / salida de caja).
"""

import logging
from datetime import date, timedelta

from src import config
from src.agents._common import to_float, fetch_opt

logger = logging.getLogger(__name__)

_TOL_DIAS  = 3
_TOL_MONTO = 1.0
_MAX_LISTA = 8   # máximo de excepciones a listar


def _buscar(monto_abs: float, fecha: date, candidatos: list[dict]) -> dict | None:
    """Primer candidato no usado que calza por monto y fecha."""
    for c in candidatos:
        if (not c["used"]
                and abs(c["monto"] - monto_abs) <= _TOL_MONTO
                and abs((c["fecha"] - fecha).days) <= _TOL_DIAS):
            c["used"] = True
            return c
    return None


# ── Conciliación que MARCA documentos como cobrados/pagados ───
_TOL_PAGO_DIAS = 120     # un pago/cobro puede ocurrir hasta N días después de la factura
_RESUELTOS = ("cobrado", "cobrada", "pagado", "pagada", "anulado", "anulada")


def _match_doc(monto_abs: float, fecha_pago: date, candidatos: list[dict]) -> dict | None:
    """Primera factura no usada con monto ≈ y emitida en/antes del pago (≤120d)."""
    for c in candidatos:
        if c["used"] or abs(c["monto"] - monto_abs) > _TOL_MONTO:
            continue
        dias = (fecha_pago - c["fecha"]).days
        if 0 <= dias <= _TOL_PAGO_DIAS:
            c["used"] = True
            return c
    return None


async def conciliar_y_marcar(conn, hasta: date, dias: int = 60) -> dict:
    """Cruza la cartola (movimientos_bancarios) con los DTE pendientes y marca:
      - abono (ingreso) ↔ factura/boleta de VENTA  → estado 'cobrado'
      - cargo (egreso)  ↔ factura de COMPRA         → estado 'pagado'
    Regla: mismo monto (±$1) y la factura emitida en/antes del movimiento (≤120d).
    Devuelve los conteos. `conn` debe tener el search_path del tenant."""
    desde = hasta - timedelta(days=dias - 1)
    movs = await conn.fetch(
        "SELECT fecha, monto FROM movimientos_bancarios WHERE fecha BETWEEN $1 AND $2 ORDER BY fecha",
        desde, hasta)
    desde_docs = hasta - timedelta(days=dias - 1 + _TOL_PAGO_DIAS)
    try:
        docs = await conn.fetch(
            "SELECT id, clase, fecha, monto_total FROM documentos_tributarios "
            "WHERE clase IN ('compra','venta') AND fecha BETWEEN $1 AND $2 "
            "AND LOWER(COALESCE(estado,'')) <> ALL($3::text[])",
            desde_docs, hasta, list(_RESUELTOS))
    except Exception:                                # noqa: BLE001 — sin clase / sin tabla
        return {"cobradas": 0, "pagadas": 0, "monto_cobrado": 0.0, "monto_pagado": 0.0,
                "movimientos": len(movs)}

    ventas  = [{"id": d["id"], "fecha": d["fecha"], "monto": to_float(d["monto_total"]), "used": False}
               for d in docs if d["clase"] == "venta"]
    compras = [{"id": d["id"], "fecha": d["fecha"], "monto": to_float(d["monto_total"]), "used": False}
               for d in docs if d["clase"] == "compra"]

    cobrar, pagar = [], []
    mc = mp = 0.0
    for m in movs:
        monto = to_float(m["monto"])
        if monto > 0:                                # abono → cobro de una venta
            c = _match_doc(monto, m["fecha"], ventas)
            if c:
                cobrar.append(c["id"]); mc += c["monto"]
        elif monto < 0:                              # cargo → pago de una compra
            c = _match_doc(abs(monto), m["fecha"], compras)
            if c:
                pagar.append(c["id"]); mp += c["monto"]

    if cobrar:
        await conn.execute("UPDATE documentos_tributarios SET estado='cobrado', "
                           "updated_at=now() WHERE id = ANY($1::int[])", cobrar)
    if pagar:
        await conn.execute("UPDATE documentos_tributarios SET estado='pagado', "
                           "updated_at=now() WHERE id = ANY($1::int[])", pagar)
    return {"cobradas": len(cobrar), "pagadas": len(pagar),
            "monto_cobrado": round(mc, 2), "monto_pagado": round(mp, 2),
            "movimientos": len(movs)}


async def calcular_conciliacion(hasta: date, dias: int = 30) -> dict:
    """Concilia la cartola con los libros en la ventana [hasta-dias+1, hasta]."""
    desde = hasta - timedelta(days=dias - 1)

    async with config.db_pool.acquire() as conn:
        movimientos = await conn.fetch(
            "SELECT fecha, monto, glosa FROM movimientos_bancarios "
            "WHERE fecha BETWEEN $1 AND $2 ORDER BY fecha", desde, hasta)
        pagos = await fetch_opt(conn,
            "SELECT fecha, monto FROM pagos WHERE fecha BETWEEN $1 AND $2", desde, hasta)
        gastos = await conn.fetch(
            "SELECT fecha, monto, proveedor FROM gastos WHERE fecha BETWEEN $1 AND $2", desde, hasta)

    # Candidatos por lado (con flag de uso). Los egresos se cruzan contra el
    # libro de gastos (salida de caja); las facturas (documentos_tributarios)
    # alimentan el IVA, no la conciliación bancaria, para no duplicar egresos.
    abonos = [{"fecha": p["fecha"], "monto": to_float(p["monto"]), "used": False}
              for p in pagos]
    cargos = [{"fecha": g["fecha"], "monto": to_float(g["monto"]),
               "ref": g["proveedor"], "used": False}
              for g in gastos]

    conciliados = 0
    monto_conciliado = 0.0
    sin_respaldo: list[dict] = []

    for m in movimientos:
        monto = to_float(m["monto"])
        fecha = m["fecha"]
        candidatos = abonos if monto > 0 else cargos
        if _buscar(abs(monto), fecha, candidatos):
            conciliados += 1
            monto_conciliado += abs(monto)
        else:
            sin_respaldo.append({
                "fecha": str(fecha), "monto": monto, "glosa": m["glosa"] or "",
            })

    # Registros de libro sin movimiento bancario que los respalde
    libro_sin_mov = [
        {"fecha": str(c["fecha"]), "monto": c["monto"], "ref": c.get("ref", "")}
        for c in (abonos + cargos) if not c["used"]
    ]

    n = len(movimientos)
    pct = round(conciliados / n * 100, 1) if n else 0.0

    return {
        "periodo": {"inicio": str(desde), "fin": str(hasta), "dias": dias},
        "tiene_cartola": n > 0,
        "resumen": {
            "movimientos":      n,
            "conciliados":      conciliados,
            "pct_conciliado":   pct,
            "monto_conciliado": round(monto_conciliado, 2),
        },
        "sin_respaldo":        sin_respaldo[:_MAX_LISTA],
        "sin_respaldo_total":  len(sin_respaldo),
        "libro_sin_movimiento": libro_sin_mov[:_MAX_LISTA],
        "libro_sin_movimiento_total": len(libro_sin_mov),
    }


def renderizar_conciliacion_markdown(data: dict) -> str:
    r = data.get("resumen", {})
    out = ["# Conciliación bancaria"]
    if not data.get("tiene_cartola"):
        out.append("\nNo hay cartola cargada en el período. "
                   "Sube tu cartola (CSV) en /api/ingest/movimientos_bancarios para conciliar.")
        return "\n".join(out)

    out.append(f"\nPeríodo: {data['periodo']['inicio']} → {data['periodo']['fin']} "
               f"({data['periodo']['dias']} días)")
    out.append(f"- Movimientos: {r['movimientos']}")
    out.append(f"- Conciliados: {r['conciliados']} ({r['pct_conciliado']}%)")
    out.append(f"- Monto conciliado: ${r['monto_conciliado']:,.0f}")

    sr = data.get("sin_respaldo", [])
    if sr:
        out.append(f"\n## Movimientos sin respaldo ({data.get('sin_respaldo_total', len(sr))})")
        for m in sr:
            out.append(f"- {m['fecha']} · ${m['monto']:,.0f} · {m['glosa']}")
    return "\n".join(out)
