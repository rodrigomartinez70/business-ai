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


def _filtros_cuentas(plantilla: list) -> set[str]:
    return {(ln.get("fuente") or "").split(":", 1)[1].strip()
            for ln in plantilla if (ln.get("fuente") or "").startswith("cuentas:")}


async def _suma_filtro(conn, filt: str, anio: int, mes_max: int) -> float:
    """Suma los saldos (período actual del año) de las cuentas que matchean el filtro,
    normalizado por tipo (income = haber-debe; resto = debe-haber). Parametrizado."""
    if "=" not in filt:
        return 0.0
    campo, valor = (s.strip() for s in filt.split("=", 1))
    base = ("SELECT pc.tipo AS tipo, COALESCE(SUM(s.haber),0) AS h, COALESCE(SUM(s.debe),0) AS d "
            "FROM plan_cuentas pc JOIN saldos_cuentas s ON s.cuenta_id = pc.id "
            "WHERE s.anio = $1 AND s.mes <= $2 AND ")
    if campo == "tipo":
        cond, arg = "pc.tipo = $3", valor
    elif campo == "grupo":
        cond, arg = "pc.grupo = $3", valor
    elif campo == "codigo":
        cond, arg = "pc.codigo LIKE $3", valor + "%"
    elif campo == "id":
        cond, arg = "pc.id_externo = ANY($3::text[])", [x.strip() for x in valor.split(",")]
    else:
        return 0.0
    try:
        rows = await conn.fetch(base + cond + " GROUP BY pc.tipo", anio, mes_max, arg)
    except Exception:                                # noqa: BLE001 — tenant sin mayor cargado
        return 0.0
    total = 0.0
    for r in rows:
        h, d = float(r["h"]), float(r["d"])
        total += (h - d) if r["tipo"] == "income" else (d - h)
    return total


async def _cuentas(filtros: set[str], anio: int, mes_max: int) -> dict:
    out: dict[str, float] = {}
    if not filtros:
        return out
    async with config.db_pool.acquire() as conn:
        for filt in filtros:
            out[filt] = await _suma_filtro(conn, filt, anio, mes_max)
    return out


def _resolver(plantilla, metricas: dict, constantes: dict, cuentas: dict | None = None) -> dict:
    """Resuelve {id: valor} top-down (ref usa líneas ya calculadas)."""
    cuentas = cuentas or {}
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
        elif f.startswith("cuentas:"):
            v = cuentas.get(f.split(":", 1)[1].strip(), 0.0)
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
    filtros = _filtros_cuentas(plantilla)
    cta_a = await _cuentas(filtros, fin_act.year, fin_act.month)      # YTD contable
    cta_b = await _cuentas(filtros, fin_ant.year, fin_ant.month)
    res_a = _resolver(plantilla, val_a, constantes or {}, cta_a)
    res_b = _resolver(plantilla, val_b, constantes or {}, cta_b)

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
        elif f.startswith("cuentas:"):
            filt = f.split(":", 1)[1].strip()
            campo = filt.split("=", 1)[0].strip() if "=" in filt else ""
            if campo not in ("tipo", "grupo", "codigo", "id"):
                errores.append(f"{et}: filtro de cuentas inválido '{filt}' "
                               f"(usá tipo=/grupo=/codigo=/id=).")
        elif not f.startswith("const:") and not f.startswith("hook:"):
            errores.append(f"{et}: fuente inválida '{f}'.")
        vistos.add(ln["id"])
    return errores
