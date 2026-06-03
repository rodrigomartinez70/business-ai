"""
Motor P&L (horizontal) — Estado de Resultados comparativo.

Estructura financiera estándar (genérica para cualquier rubro), comparando el
año actual YTD (1-ene → corte) contra el año anterior en el mismo rango.

El vertical aporta solo los hooks de dónde salen los ingresos y el costo de
ventas; el resto (estructura, gastos operativos por categoría, subtotales,
comparativa) es común.

Hooks (async, reciben conexión scopeada al tenant):
    ingresos_brutos_fn(conn, ini, fin) -> float
    costo_ventas_fn(conn, ini, fin)    -> float
    devoluciones_fn(conn, ini, fin)    -> float   (opcional; default 0)

Líneas sin fuente de dato en el modelo actual (depreciación, financieros, otros,
impuesto) salen en 0 salvo que se configuren en config.yaml → `pnl`.
"""

from datetime import date

from src import config
from src.agents._common import to_float, fmt_moneda

# Mapeo categoría de gasto → bucket operativo del P&L. El resto → "generales".
_BUCKET = {
    "Marketing":      "ventas_marketing",
    "Administración": "administracion",
    "Honorarios":     "administracion",
}


def _anio_atras(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:           # 29-feb
        return d.replace(year=d.year - 1, day=28)


async def _gastos_buckets(conn, ini: date, fin: date) -> dict:
    rows = await conn.fetch("""
        SELECT cg.nombre AS cat, COALESCE(SUM(g.monto), 0) AS monto
        FROM gastos g LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
        WHERE g.fecha BETWEEN $1 AND $2
        GROUP BY cg.nombre
    """, ini, fin)
    b = {"ventas_marketing": 0.0, "administracion": 0.0, "generales": 0.0}
    for r in rows:
        bucket = _BUCKET.get(r["cat"] or "", "generales")
        b[bucket] += to_float(r["monto"])
    return b


async def _periodo(conn, ini, fin, ingresos_brutos_fn, costo_ventas_fn, devoluciones_fn, cfg_pnl) -> dict:
    brutos = await ingresos_brutos_fn(conn, ini, fin)
    devol  = await devoluciones_fn(conn, ini, fin) if devoluciones_fn else 0.0
    netos  = brutos - devol
    costo  = await costo_ventas_fn(conn, ini, fin)
    margen = netos - costo

    g = await _gastos_buckets(conn, ini, fin)
    gastos_op = g["ventas_marketing"] + g["administracion"] + g["generales"]

    ebitda     = margen - gastos_op
    dep_amort  = float(cfg_pnl.get("depreciacion_amortizacion", 0) or 0)
    ebit       = ebitda - dep_amort
    financieros = float(cfg_pnl.get("resultado_financiero", 0) or 0)
    otros       = float(cfg_pnl.get("otros_no_operativos", 0) or 0)
    antes_imp   = ebit + financieros + otros
    tasa_imp    = float(cfg_pnl.get("tasa_impuesto_renta", 0) or 0)
    impuesto    = round(max(0.0, antes_imp) * tasa_imp, 2)
    neto        = antes_imp - impuesto

    return {
        "ingresos_brutos": brutos, "devoluciones": devol, "ingresos_netos": netos,
        "costo_ventas": costo, "margen_bruto": margen,
        "g_ventas_marketing": g["ventas_marketing"], "g_administracion": g["administracion"],
        "g_generales": g["generales"], "gastos_operativos": gastos_op,
        "ebitda": ebitda, "dep_amort": dep_amort, "ebit": ebit,
        "financieros": financieros, "otros": otros, "antes_impuestos": antes_imp,
        "impuesto": impuesto, "resultado_neto": neto,
    }


def _linea(concepto, tipo, a, b, key, signo=1):
    av = round(a[key] * signo, 2)
    bv = round(b[key] * signo, 2)
    var_abs = round(av - bv, 2)
    var_pct = round((av - bv) / abs(bv) * 100, 1) if bv else None
    return {"concepto": concepto, "tipo": tipo, "actual": av, "anterior": bv,
            "var_abs": var_abs, "var_pct": var_pct}


async def calcular_pnl_comparativo(hasta, ingresos_brutos_fn, costo_ventas_fn,
                                   devoluciones_fn=None) -> dict:
    """P&L comparativo YTD (año actual vs año anterior, mismo rango)."""
    ini_act = date(hasta.year, 1, 1)
    fin_act = hasta
    fin_ant = _anio_atras(hasta)
    ini_ant = date(fin_ant.year, 1, 1)
    cfg_pnl = (config.get_config() or {}).get("pnl", {})

    async with config.db_pool.acquire() as conn:
        a = await _periodo(conn, ini_act, fin_act, ingresos_brutos_fn, costo_ventas_fn, devoluciones_fn, cfg_pnl)
        b = await _periodo(conn, ini_ant, fin_ant, ingresos_brutos_fn, costo_ventas_fn, devoluciones_fn, cfg_pnl)

    L = _linea
    lineas = [
        L("Ingresos Brutos por Ventas",                       "detalle",  a, b, "ingresos_brutos"),
        L("(-) Devoluciones, Rebajas y Descuentos",           "detalle",  a, b, "devoluciones", -1),
        L("= Ingresos Netos por Ventas",                      "subtotal", a, b, "ingresos_netos"),
        L("(-) Costo de Ventas",                              "detalle",  a, b, "costo_ventas", -1),
        L("= Margen Bruto",                                   "subtotal", a, b, "margen_bruto"),
        L("(-) Gastos Operativos",                            "header",   a, b, "gastos_operativos", -1),
        L("• Gastos de Ventas y Marketing",                   "sub",      a, b, "g_ventas_marketing", -1),
        L("• Gastos de Administración",                       "sub",      a, b, "g_administracion", -1),
        L("• Gastos Generales",                               "sub",      a, b, "g_generales", -1),
        L("= EBITDA",                                         "subtotal", a, b, "ebitda"),
        L("(-) Depreciación y Amortización",                  "detalle",  a, b, "dep_amort", -1),
        L("= EBIT (Resultado Operativo)",                     "subtotal", a, b, "ebit"),
        L("(+/-) Resultado Financiero (neto)",                "detalle",  a, b, "financieros"),
        L("(+/-) Otros Ingresos / Gastos no operativos",      "detalle",  a, b, "otros"),
        L("= Resultado Antes de Impuestos",                   "subtotal", a, b, "antes_impuestos"),
        L("(-) Impuesto a la Renta",                          "detalle",  a, b, "impuesto", -1),
        L("= Resultado Neto",                                 "total",    a, b, "resultado_neto"),
    ]

    margen_pct = round(a["margen_bruto"] / a["ingresos_netos"] * 100, 1) if a["ingresos_netos"] else 0
    return {
        "periodo": {
            "actual":   {"inicio": str(ini_act), "fin": str(fin_act), "label": f"{ini_act.year} YTD"},
            "anterior": {"inicio": str(ini_ant), "fin": str(fin_ant), "label": f"{ini_ant.year} YTD"},
        },
        "lineas": lineas,
        "resumen": {
            "ingresos_netos": a["ingresos_netos"],
            "margen_bruto": a["margen_bruto"], "margen_bruto_pct": margen_pct,
            "ebitda": a["ebitda"], "resultado_neto": a["resultado_neto"],
            "var_ingresos_pct":  _linea("", "", a, b, "ingresos_netos")["var_pct"],
            "var_resultado_pct": _linea("", "", a, b, "resultado_neto")["var_pct"],
        },
    }


# ── Render ───────────────────────────────────────────────────

def _vpct(p):
    return "—" if p is None else f"{p:+.1f}%"


def renderizar_pnl_html(data: dict, cfg: dict) -> str:
    """Tabla comparativa para el dashboard (sin la tarjeta envolvente)."""
    per = data["periodo"]
    filas = ""
    for ln in data["lineas"]:
        peso = "700" if ln["tipo"] in ("subtotal", "total", "header") else "400"
        bg   = "background:#f9fafb;" if ln["tipo"] == "total" else ""
        sang = "padding-left:18px;color:#6b7280;" if ln["tipo"] == "sub" else ""
        vcls = "pos" if (ln["var_abs"] or 0) >= 0 else "neg"
        filas += (
            f'<tr style="{bg}"><td style="font-weight:{peso};{sang}">{ln["concepto"]}</td>'
            f'<td style="text-align:right;font-weight:{peso};">{fmt_moneda(ln["actual"], cfg)}</td>'
            f'<td style="text-align:right;color:#6b7280;">{fmt_moneda(ln["anterior"], cfg)}</td>'
            f'<td style="text-align:right;">{fmt_moneda(ln["var_abs"], cfg)}</td>'
            f'<td style="text-align:right;" class="{vcls}">{_vpct(ln["var_pct"])}</td></tr>'
        )
    return (
        '<table class="dt"><tr><th>Concepto</th>'
        f'<th>{per["actual"]["label"]}</th><th>{per["anterior"]["label"]}</th>'
        '<th>Var $</th><th>Var %</th></tr>'
        f'{filas}</table>'
    )


def renderizar_pnl_markdown(data: dict, cfg: dict) -> str:
    per = data["periodo"]
    out = [f"# P&L comparativo — {per['actual']['label']} vs {per['anterior']['label']}\n",
           f"| Concepto | {per['actual']['label']} | {per['anterior']['label']} | Var $ | Var % |",
           "|---|--:|--:|--:|--:|"]
    for ln in data["lineas"]:
        out.append(f"| {ln['concepto']} | {fmt_moneda(ln['actual'], cfg)} | "
                   f"{fmt_moneda(ln['anterior'], cfg)} | {fmt_moneda(ln['var_abs'], cfg)} | "
                   f"{_vpct(ln['var_pct'])} |")
    return "\n".join(out)
