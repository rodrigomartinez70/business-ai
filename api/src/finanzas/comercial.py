"""
Módulo "Ventas / Comercial" config-driven (universal).

Si el tenant tiene un bloque `ventas:` en su config, este módulo lo arma desde
fuentes con nombre (KPIs por metrica/formula + tablas por `tabla:`), igual para
cualquier rubro. Si no hay bloque, el vertical usa su sección actual (sin regresión).
"""

from datetime import date

from .. import config
from ..metricas import formula
from ..metricas.registry import (obtener as _metrica, obtener_tabla,
                                  catalogo, catalogo_tablas)
from ..render import _card, _kpis, _fm


def tiene_config(cfg: dict) -> bool:
    return bool((cfg or {}).get("ventas"))


def _fmt(val, tipo: str, cfg: dict) -> str:
    if val is None:
        return "—"
    if tipo == "moneda":
        return _fm(val, cfg)
    if tipo == "pct":
        return f"{val:.1f}%"
    if tipo == "numero":
        return f"{val:,.0f}"
    return str(val)


def _tabla_html(titulo: str, cols: list, rows: list, cfg: dict) -> str:
    if not rows:
        return ""
    th = "".join(f"<th>{lbl}</th>" for _c, lbl, _t in cols)
    trs = ""
    for r in rows:
        trs += "<tr>" + "".join(f'<td>{_fmt(r.get(c), t, cfg)}</td>' for c, _l, t in cols) + "</tr>"
    pre = (f'<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">{titulo}</div>'
           if titulo else "")
    return pre + f'<table class="dt"><tr>{th}</tr>{trs}</table>'


async def render(cfg: dict, vertical: str, ini: date, fin: date) -> str:
    vcfg = cfg.get("ventas") or {}
    kpis_cfg = vcfg.get("kpis", [])
    tablas_cfg = vcfg.get("tablas", [])

    nombres: set[str] = set()
    for k in kpis_cfg:
        if k.get("metrica"):
            nombres.add(k["metrica"])
        elif k.get("formula"):
            try:
                nombres |= formula.nombres_referenciados(k["formula"])
            except formula.FormulaError:
                pass

    metr: dict[str, float] = {}
    tablas_render = []
    async with config.db_pool.acquire() as conn:
        for n in nombres:
            m = _metrica(n, vertical)
            if m:
                metr[n] = await m.fn(conn, ini, fin)
        for t in tablas_cfg:
            src = (t.get("fuente") or "")
            ft = obtener_tabla(src.split(":", 1)[1], vertical) if src.startswith("tabla:") else None
            rows = await ft.fn(conn, ini, fin) if ft else []
            tablas_render.append((t.get("titulo", ""), ft.columnas if ft else [], rows))

    kpi_rows = []
    for k in kpis_cfg:
        try:
            v = metr.get(k["metrica"], 0.0) if k.get("metrica") \
                else formula.evaluar(k.get("formula", ""), metr)
        except formula.FormulaError:
            v = 0.0
        kpi_rows.append((k.get("nombre") or k.get("clave"), _fmt(v, k.get("unidad", "numero"), cfg)))

    body = _kpis(kpi_rows)
    for titulo, cols, rows in tablas_render:
        body += _tabla_html(titulo, cols, rows, cfg)
    return _card("📊 " + vcfg.get("titulo", "Ventas / Comercial"), body)


def validar(vertical: str | None, cfg: dict) -> list[str]:
    """Valida el bloque ventas: del config (métricas/tablas conocidas). Sin DB."""
    vcfg = (cfg or {}).get("ventas")
    if not vcfg:
        return []
    errores: list[str] = []
    metr_disp = {m.nombre for m in catalogo(vertical)}
    tab_disp = {t.nombre for t in catalogo_tablas(vertical)}
    for i, k in enumerate(vcfg.get("kpis", [])):
        et = f"Ventas KPI #{i + 1} ({k.get('clave') or k.get('nombre') or '?'})"
        if k.get("metrica") and k["metrica"] not in metr_disp:
            errores.append(f"{et}: métrica desconocida '{k['metrica']}'.")
        if k.get("formula"):
            try:
                d = formula.nombres_referenciados(k["formula"]) - metr_disp
                if d:
                    errores.append(f"{et}: métricas desconocidas: {', '.join(sorted(d))}.")
            except formula.FormulaError as e:
                errores.append(f"{et}: fórmula inválida — {e}.")
    for i, t in enumerate(vcfg.get("tablas", [])):
        src = (t.get("fuente") or "")
        nombre = src.split(":", 1)[1] if src.startswith("tabla:") else ""
        if nombre not in tab_disp:
            errores.append(f"Ventas tabla #{i + 1}: fuente de tabla desconocida '{src}'.")
    return errores
