"""
P&L desde plantilla declarativa (F2) — la porción ajustable por empresa.

Cuando el tenant tiene `config.pnl.plantilla`, el P&L se arma con esa plantilla
(líneas que referencian el catálogo de métricas); si no, se usa el default del
vertical (finanzas/pnl.py, sin cambios). La salida tiene la MISMA forma que el
motor default (lineas + resumen + periodo) para que el render no cambie.

Cada línea: {id, etiqueta, tipo: detalle|subtotal|total|header|sub, fuente, signo}
fuente: metrica:<n> | formula:<expr> | const:<clave> | ref:<id,id,…>
"""

from datetime import date

from .. import config
from ..metricas import formula
from ..metricas.registry import obtener, catalogo
from .pnl import _anio_atras


def _var(av: float, bv: float):
    return round((av - bv) / abs(bv) * 100, 1) if bv else None


def _necesarias(plantilla: list) -> set[str]:
    nombres: set[str] = set()
    for ln in plantilla:
        f = (ln.get("fuente") or "")
        if f.startswith("metrica:"):
            nombres.add(f.split(":", 1)[1].strip())
        elif f.startswith("formula:"):
            try:
                nombres |= formula.nombres_referenciados(f.split(":", 1)[1])
            except formula.FormulaError:
                pass
    return nombres


async def _metricas(vertical, nombres, ini, fin) -> dict:
    valores: dict[str, float] = {}
    if not nombres:
        return valores
    async with config.db_pool.acquire() as conn:
        for n in nombres:
            m = obtener(n, vertical)
            valores[n] = (await m.fn(conn, ini, fin)) if m else 0.0
    return valores


def _resolver(plantilla, metricas: dict, constantes: dict) -> dict:
    """Resuelve {id: valor} top-down (ref usa líneas ya calculadas)."""
    res: dict[str, float] = {}
    for ln in plantilla:
        f = (ln.get("fuente") or "")
        signo = ln.get("signo", 1)
        if f.startswith("metrica:"):
            v = metricas.get(f.split(":", 1)[1].strip(), 0.0)
        elif f.startswith("formula:"):
            v = formula.evaluar(f.split(":", 1)[1], metricas)
        elif f.startswith("const:"):
            v = float(constantes.get(f.split(":", 1)[1].strip(), 0) or 0)
        elif f.startswith("ref:"):
            v = sum(res.get(i.strip(), 0.0) for i in f.split(":", 1)[1].split(","))
        else:
            v = 0.0
        res[ln.get("id")] = round(v * signo, 2)
    return res


def _pick(d: dict, *ids):
    for i in ids:
        if i in d:
            return d[i]
    return 0.0


async def calcular_desde_plantilla(vertical, plantilla, constantes, hasta) -> dict:
    ini_act, fin_act = date(hasta.year, 1, 1), hasta
    fin_ant = _anio_atras(hasta)
    ini_ant = date(fin_ant.year, 1, 1)

    nombres = _necesarias(plantilla)
    val_a = await _metricas(vertical, nombres, ini_act, fin_act)
    val_b = await _metricas(vertical, nombres, ini_ant, fin_ant)
    res_a = _resolver(plantilla, val_a, constantes or {})
    res_b = _resolver(plantilla, val_b, constantes or {})

    lineas = []
    for ln in plantilla:
        lid = ln.get("id")
        av, bv = res_a.get(lid, 0.0), res_b.get(lid, 0.0)
        lineas.append({"concepto": ln.get("etiqueta", lid), "tipo": ln.get("tipo", "detalle"),
                       "actual": av, "anterior": bv, "var_abs": round(av - bv, 2),
                       "var_pct": _var(av, bv)})

    # resumen por convención de ids (con fallbacks); resultado = id conocido o última línea 'total'
    neto_id = next((ln.get("id") for ln in reversed(plantilla)
                    if ln.get("id") in ("resultado_neto", "resultado") or ln.get("tipo") == "total"), None)
    ing_a = _pick(res_a, "ingresos_netos", "ing_netos", "ingresos", "ing_brutos")
    ing_b = _pick(res_b, "ingresos_netos", "ing_netos", "ingresos", "ing_brutos")
    margen_a = _pick(res_a, "margen_bruto", "margen")
    neto_a = res_a.get(neto_id, 0.0)
    neto_b = res_b.get(neto_id, 0.0)
    return {
        "periodo": {
            "actual":   {"inicio": str(ini_act), "fin": str(fin_act), "label": f"{ini_act.year} YTD"},
            "anterior": {"inicio": str(ini_ant), "fin": str(fin_ant), "label": f"{ini_ant.year} YTD"},
        },
        "lineas": lineas,
        "resumen": {
            "ingresos_netos": ing_a, "margen_bruto": margen_a,
            "margen_bruto_pct": round(margen_a / ing_a * 100, 1) if ing_a else 0,
            "ebitda": _pick(res_a, "ebitda"), "resultado_neto": neto_a,
            "var_ingresos_pct": _var(ing_a, ing_b),
            "var_resultado_pct": _var(neto_a, neto_b),
        },
    }


def validar_pnl(vertical: str | None, pnl_cfg: dict) -> list[str]:
    """Valida la plantilla de P&L del config (sin DB). Devuelve errores."""
    if not isinstance(pnl_cfg, dict) or not pnl_cfg.get("plantilla"):
        return []
    plantilla = pnl_cfg["plantilla"]
    if not isinstance(plantilla, list):
        return ["pnl.plantilla debe ser una lista de líneas."]
    errores: list[str] = []
    disponibles = {m.nombre for m in catalogo(vertical)}
    vistos: set[str] = set()
    for i, ln in enumerate(plantilla):
        et = f"P&L línea #{i + 1} ({ln.get('id') or '?'})"
        if not isinstance(ln, dict) or not ln.get("id"):
            errores.append(f"{et}: falta 'id'."); continue
        if not ln.get("fuente"):
            errores.append(f"{et}: falta 'fuente'."); continue
        f = ln["fuente"]
        if f.startswith("metrica:"):
            n = f.split(":", 1)[1].strip()
            if n not in disponibles:
                errores.append(f"{et}: métrica desconocida '{n}'.")
        elif f.startswith("formula:"):
            try:
                desc = formula.nombres_referenciados(f.split(":", 1)[1]) - disponibles
                if desc:
                    errores.append(f"{et}: métricas desconocidas: {', '.join(sorted(desc))}.")
            except formula.FormulaError as e:
                errores.append(f"{et}: fórmula inválida — {e}.")
        elif f.startswith("ref:"):
            for r in f.split(":", 1)[1].split(","):
                if r.strip() not in vistos:
                    errores.append(f"{et}: ref '{r.strip()}' debe ser una línea anterior.")
        elif not f.startswith("const:") and not f.startswith("hook:"):
            errores.append(f"{et}: fuente inválida '{f}'.")
        vistos.add(ln["id"])
    return errores
