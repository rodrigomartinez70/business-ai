"""
Agente Presupuestario (horizontal).

Compara el presupuesto cargado (tabla `presupuesto`) contra la ejecución real
acumulada del año (YTD: enero → mes de corte):
  - ingresos reales  = cobros del período (tabla pagos);
  - gastos reales    = tabla gastos agrupada por categoría.
Reporta variación por línea (real − presupuesto) y desviaciones que superan el
umbral. Sin LLM — SQL puro. Si no hay presupuesto cargado, lo informa.
"""

import logging
from datetime import date

from src import config
from src.agents._common import to_float

logger = logging.getLogger(__name__)

UMBRAL_DESVIO_PCT = 15        # |variación| ≥ 15% → desviación a revisar


def _var(real: float, presu: float) -> float | None:
    if presu == 0:
        return None
    return round((real - presu) / presu * 100, 1)


async def calcular_presupuesto(hasta: date) -> dict:
    anio = hasta.year
    ini  = date(anio, 1, 1)

    async with config.db_pool.acquire() as conn:
        presu = await conn.fetch(
            """SELECT tipo, LOWER(categoria) AS categoria, SUM(monto) AS monto
                 FROM presupuesto
                WHERE anio = $1 AND mes <= $2
                GROUP BY tipo, LOWER(categoria)""",
            anio, hasta.month)
        if not presu:
            return {"corte": str(hasta), "anio": anio, "tiene_presupuesto": False}

        ingresos_real = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE fecha BETWEEN $1 AND $2",
            ini, hasta) or 0)
        gastos_real = await conn.fetch(
            """SELECT LOWER(COALESCE(cg.nombre, 'sin categoría')) AS categoria,
                      SUM(g.monto) AS monto
                 FROM gastos g LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
                WHERE g.fecha BETWEEN $1 AND $2
                GROUP BY LOWER(COALESCE(cg.nombre, 'sin categoría'))""",
            ini, hasta)

    real_gastos = {r["categoria"]: to_float(r["monto"]) for r in gastos_real}
    presu_ing = sum(to_float(p["monto"]) for p in presu if p["tipo"] == "ingreso")
    presu_gastos = {p["categoria"]: to_float(p["monto"]) for p in presu if p["tipo"] == "gasto"}

    lineas, desviaciones = [], []

    # Ingresos (más venta que lo presupuestado es favorable)
    if presu_ing:
        v = _var(ingresos_real, presu_ing)
        linea = {"tipo": "ingreso", "categoria": "ingresos", "presupuesto": round(presu_ing, 2),
                 "real": round(ingresos_real, 2),
                 "variacion": round(ingresos_real - presu_ing, 2), "var_pct": v}
        lineas.append(linea)
        if v is not None and abs(v) >= UMBRAL_DESVIO_PCT:
            desviaciones.append({**linea, "favorable": ingresos_real >= presu_ing})

    # Gastos (gastar más que lo presupuestado es desfavorable)
    for cat in sorted(set(presu_gastos) | set(real_gastos)):
        p = presu_gastos.get(cat, 0.0)
        r = real_gastos.get(cat, 0.0)
        v = _var(r, p)
        linea = {"tipo": "gasto", "categoria": cat, "presupuesto": round(p, 2),
                 "real": round(r, 2), "variacion": round(r - p, 2), "var_pct": v}
        lineas.append(linea)
        if v is not None and abs(v) >= UMBRAL_DESVIO_PCT:
            desviaciones.append({**linea, "favorable": r <= p})

    total_presu_gasto = sum(presu_gastos.values())
    total_real_gasto  = sum(real_gastos.values())

    return {
        "corte": str(hasta),
        "anio": anio,
        "tiene_presupuesto": True,
        "ingresos": {"presupuesto": round(presu_ing, 2), "real": round(ingresos_real, 2),
                     "var_pct": _var(ingresos_real, presu_ing)},
        "gastos": {"presupuesto": round(total_presu_gasto, 2), "real": round(total_real_gasto, 2),
                   "var_pct": _var(total_real_gasto, total_presu_gasto)},
        "lineas": lineas,
        "desviaciones": sorted(desviaciones, key=lambda x: -abs(x["var_pct"] or 0)),
    }


def renderizar_presupuesto_markdown(data: dict) -> str:
    if not data.get("tiene_presupuesto"):
        return ("# Presupuesto\n\nNo hay presupuesto cargado para el año "
                f"{data.get('anio')}. Cargá la tabla `presupuesto` (año, mes, tipo, "
                "categoría, monto) para activar el control presupuestario.")
    ing, gas = data["ingresos"], data["gastos"]
    out = ["# Control Presupuestario (YTD)",
           f"\nAño {data['anio']} · corte {data['corte']}",
           f"- Ingresos: real ${ing['real']:,.0f} vs presup. ${ing['presupuesto']:,.0f} "
           f"({_pct(ing['var_pct'])})",
           f"- Gastos: real ${gas['real']:,.0f} vs presup. ${gas['presupuesto']:,.0f} "
           f"({_pct(gas['var_pct'])})"]
    if data["desviaciones"]:
        out.append(f"\n## Desviaciones ≥ {UMBRAL_DESVIO_PCT}%")
        for d in data["desviaciones"]:
            flag = "✅" if d.get("favorable") else "⚠️"
            out.append(f"- {flag} {d['categoria']}: real ${d['real']:,.0f} vs "
                       f"${d['presupuesto']:,.0f} ({_pct(d['var_pct'])})")
    return "\n".join(out)


def _pct(v) -> str:
    return f"{v:+.1f}%" if v is not None else "s/d"
