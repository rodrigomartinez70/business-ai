"""
KPIs por fórmula (F1) — evalúa los KPIs declarados en `config.kpis` que usan
`metrica` o `formula` (los que tienen `sql` los maneja el legado agents/alertas.py).
"""

import logging
from datetime import date, timedelta

from .. import config
from . import formula
from .registry import obtener, catalogo

logger = logging.getLogger(__name__)


def solo_formula(kpis_cfg: list) -> list:
    return [k for k in (kpis_cfg or []) if "formula" in k or "metrica" in k]


def validar(vertical: str | None, kpis_cfg: list) -> list[str]:
    """Errores de los KPIs por fórmula (estructura + métricas conocidas). Sin DB."""
    errores: list[str] = []
    disponibles = {m.nombre for m in catalogo(vertical)}
    for i, k in enumerate(solo_formula(kpis_cfg)):
        et = f"KPI #{i + 1} ({k.get('clave') or k.get('nombre') or '?'})"
        if not k.get("clave"):
            errores.append(f"{et}: falta 'clave'.")
        if not (k.get("formula") or k.get("metrica")):
            errores.append(f"{et}: falta 'formula' o 'metrica'.")
        if k.get("metrica") and k["metrica"] not in disponibles:
            errores.append(f"{et}: métrica desconocida '{k['metrica']}'.")
        if k.get("formula"):
            try:
                desconocidas = formula.nombres_referenciados(k["formula"]) - disponibles
                if desconocidas:
                    errores.append(f"{et}: métricas desconocidas en la fórmula: "
                                   f"{', '.join(sorted(desconocidas))}.")
            except formula.FormulaError as e:
                errores.append(f"{et}: fórmula inválida — {e}.")
    return errores


async def _valores(vertical: str | None, nombres: set[str], ini: date, fin: date) -> dict:
    valores: dict[str, float] = {}
    if not nombres:
        return valores
    async with config.db_pool.acquire() as conn:
        for nombre in nombres:
            m = obtener(nombre, vertical)
            if m is not None:
                try:
                    valores[nombre] = await m.fn(conn, ini, fin)
                except Exception as e:                   # noqa: BLE001
                    logger.warning(f"[kpis] métrica '{nombre}' falló: {e}")
    return valores


def _estado(v: float, k: dict) -> str:
    mn, mx = k.get("umbral_min"), k.get("umbral_max")
    if (mn is not None and v < mn) or (mx is not None and v > mx):
        return "alerta"
    return "ok"


async def evaluar(vertical: str | None, kpis_cfg: list, fin: date, dias: int = 30) -> list[dict]:
    """Evalúa los KPIs por fórmula del tenant para la ventana [fin-dias+1, fin]."""
    ini = fin - timedelta(days=dias - 1)
    items = solo_formula(kpis_cfg)
    necesarias: set[str] = set()
    for k in items:
        if k.get("metrica"):
            necesarias.add(k["metrica"])
        elif k.get("formula"):
            try:
                necesarias |= formula.nombres_referenciados(k["formula"])
            except formula.FormulaError:
                pass
    valores = await _valores(vertical, necesarias, ini, fin)

    out = []
    for k in items:
        base = {"clave": k.get("clave"), "nombre": k.get("nombre") or k.get("clave"),
                "unidad": k.get("unidad", "numero"),
                "umbral_min": k.get("umbral_min"), "umbral_max": k.get("umbral_max")}
        try:
            v = valores.get(k["metrica"], 0.0) if k.get("metrica") \
                else formula.evaluar(k["formula"], valores)
            out.append({**base, "valor": round(float(v), 2), "estado": _estado(v, k)})
        except formula.FormulaError as e:
            out.append({**base, "valor": None, "estado": "error", "error": str(e)})
    return out
