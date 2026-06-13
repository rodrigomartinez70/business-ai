"""
Informe Financiero (horizontal) — un único correo top-down que fusiona el
dashboard semanal del vertical con el panel financiero (CFO, Tesorería, CxC/CxP,
Presupuesto).

Estructura pirámide:
  1. Resumen ejecutivo: números grandes (KPIs) + semáforo + puntos clave (CFO).
  2. Índice navegable.
  3. Temas en orden de impacto financiero, cada uno titular → cifras → detalle:
     Rentabilidad · Liquidez & Tesorería · Cobros & Pagos · Presupuesto ·
     Ventas/Comercial · Gastos · Tributario · Marketing · Cierre · Contexto (IPC).

No calcula nada propio: orquesta `calcular_dashboard()` (vertical) + `calcular_panel()`
(horizontal) y reutiliza los renderers existentes.
"""

import logging
from datetime import date

from src.render import _CSS
from src.verticals import dispatch
from src.finanzas.panel import (
    calcular_panel, _sec_tesoreria, _sec_cxc, _sec_cxp, _sec_presupuesto,
    _m, _COLOR,
)

logger = logging.getLogger(__name__)

# Módulos del informe (clave estable, ancla, título). El config del tenant
# (report.modulos) puede desactivar cualquiera; clave ausente = activo.
MODULOS = [
    ("rentabilidad", "sec-rentabilidad", "Rentabilidad (P&L)"),
    ("liquidez",     "sec-liquidez",     "Liquidez & Tesorería"),
    ("cobros_pagos", "sec-cobros-pagos", "Cobros & Pagos"),
    ("presupuesto",  "sec-presupuesto",  "Presupuesto"),
    ("comercial",    "sec-comercial",    "Ventas / Comercial"),
    ("gastos",       "sec-gastos",       "Gastos"),
    ("tributario",   "sec-tributario",   "Tributario"),
    ("marketing",    "sec-marketing",    "Marketing"),
    ("cierre",       "sec-cierre",       "Cierre del período"),
    ("ipc",          "sec-ipc",          "Contexto económico (IPC)"),
]


def modulo_activo(cfg: dict, clave: str) -> bool:
    mods = (cfg.get("report") or {}).get("modulos") or {}
    return mods.get(clave, True)


async def calcular_informe(corte: date | None = None) -> dict:
    corte = corte or date.today()
    dash  = await dispatch.dashboard().calcular_dashboard()
    panel = await calcular_panel(corte)
    return {"corte": str(corte), "dash": dash, "panel": panel}


# ─────────────────────────────────────────────────────────────
# Render top-down
# ─────────────────────────────────────────────────────────────

def _tile(label: str, valor: str, sub: str = "", color: str = "#111827") -> str:
    sub_html = (f'<div style="font-size:11px;color:#6b7280;margin-top:2px;">{sub}</div>'
                if sub else "")
    return (
        '<td style="padding:6px;" width="33%">'
        '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 12px;text-align:center;">'
        f'<div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px;">{label}</div>'
        f'<div style="font-size:22px;font-weight:700;color:{color};margin-top:4px;">{valor}</div>'
        f'{sub_html}</div></td>'
    )


def _pct_txt(v) -> str:
    return f"{v:+.0f}% vs año ant." if v is not None else ""


def _resumen_ejecutivo(panel: dict, pnl: dict) -> str:
    cfo  = panel["cfo"]
    teso = panel["tesoreria"]
    r    = pnl.get("resumen", {})
    sem  = cfo["semaforo"]
    col  = _COLOR.get(sem, "#6b7280")

    res = r.get("resultado_neto", 0)
    tiles1 = (
        _tile("Resultado neto", _m(res), _pct_txt(r.get("var_resultado_pct")),
              "#16a34a" if res >= 0 else "#dc2626")
        + _tile("Margen bruto", f'{r.get("margen_bruto_pct", 0):.0f}%')
        + _tile("Caja estimada", _m(teso.get("caja_estimada")),
                f'proy. 8 sem {_m(teso.get("caja_proyectada_8sem"))}')
    )
    tiles2 = (
        _tile("Ingresos netos", _m(r.get("ingresos_netos")), _pct_txt(r.get("var_ingresos_pct")))
        + _tile("Por cobrar", _m(panel["cuentas_por_cobrar"].get("total_por_cobrar")),
                f'DSO {panel["cuentas_por_cobrar"]["dso"]:.0f}d' if panel["cuentas_por_cobrar"].get("dso") is not None else "")
        + _tile("Por pagar", _m(panel["cuentas_por_pagar"].get("total_por_pagar")),
                f'vencido {_m(panel["cuentas_por_pagar"].get("vencido"))}')
    )

    puntos = cfo.get("puntos_clave", [])
    if puntos:
        lis = "".join(
            f'<li style="margin:4px 0;color:#374151;font-size:13px;">'
            f'<span style="color:{_COLOR.get(p["nivel"], "#6b7280")};font-weight:700;">&#9679;</span> '
            f'{p["texto"]}</li>' for p in puntos)
        puntos_html = (
            '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 16px;margin:6px 6px 0;">'
            '<div style="font-size:12px;font-weight:700;color:#374151;margin-bottom:6px;">Puntos clave</div>'
            f'<ul style="margin:0;padding-left:4px;list-style:none;">{lis}</ul></div>')
    else:
        puntos_html = ('<div style="padding:10px 16px;color:#16a34a;font-size:13px;">'
                       'Sin alertas: indicadores dentro de lo esperado.</div>')

    badge = (f'<span style="display:inline-block;padding:3px 12px;border-radius:12px;background:{col};'
             f'color:#fff;font-size:12px;font-weight:700;text-transform:uppercase;">{sem}</span>')

    return (
        f'<div style="margin:0 0 6px;text-align:center;">{badge}</div>'
        '<table width="100%" style="border-collapse:collapse;"><tr>'
        f'{tiles1}</tr><tr>{tiles2}</tr></table>'
        f'{puntos_html}'
    )


# Orden top-down: (id_ancla, título, builder que devuelve el HTML de la sección)
def _indice(items: list[tuple[str, str]]) -> str:
    lis = "".join(
        f'<li style="margin:5px 0;"><a href="#{aid}" style="color:#2563eb;text-decoration:none;font-size:13px;">'
        f'{i+1}. {titulo}</a></li>'
        for i, (aid, titulo) in enumerate(items))
    return (
        '<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 18px;margin:14px 6px;">'
        '<div style="font-size:12px;font-weight:700;color:#374151;text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px;">Contenido</div>'
        f'<ol style="margin:0;padding-left:18px;">{lis}</ol></div>')


def _bloque(aid: str, n: int, titulo: str, contenido: str) -> str:
    if not contenido or not contenido.strip():
        return ""
    return (
        f'<a name="{aid}"></a>'
        f'<div style="margin:22px 6px 8px;border-top:2px solid #1f2937;padding-top:10px;">'
        f'<div style="font-size:16px;font-weight:700;color:#1f2937;">{n}. {titulo}</div></div>'
        f'<div style="margin:0 6px;">{contenido}</div>')


def renderizar_informe_html(data: dict, cfg: dict, biz: str) -> str:
    dash  = data["dash"]
    panel = data["panel"]
    secs  = dispatch.dashboard().secciones_html(dash, cfg)

    # Liquidez = Tesorería (rica) + conciliación bancaria del dashboard
    liquidez = _sec_tesoreria(panel["tesoreria"]) + secs.get("conciliacion", "")
    cobros_pagos = _sec_cxc(panel["cuentas_por_cobrar"]) + _sec_cxp(panel["cuentas_por_pagar"])
    presupuesto  = _sec_presupuesto(panel["presupuesto"])
    # Estado DTE: solo si la capacidad SII está activa (default on → sin regresión).
    _sii_dte = ((cfg.get("sii") or {}).get("estado_dte", True))
    tributario   = secs.get("tributario", "") + (secs.get("estado_dte", "") if _sii_dte else "")

    contenido = {
        "rentabilidad": secs.get("pnl", ""),
        "liquidez":     liquidez,
        "cobros_pagos": cobros_pagos,
        "presupuesto":  presupuesto,
        "comercial":    secs.get("comercial", ""),
        "gastos":       secs.get("gastos", ""),
        "tributario":   tributario,
        "marketing":    secs.get("marketing", ""),
        "cierre":       secs.get("cierre", ""),
        "ipc":          secs.get("ipc", ""),
    }
    # Solo los módulos activos en el config del tenant (report.modulos).
    bloques = [(aid, tit, contenido[clave]) for clave, aid, tit in MODULOS
               if modulo_activo(cfg, clave)]
    # Solo numeramos/indexamos los bloques con contenido
    presentes = [(aid, tit) for aid, tit, html in bloques if html and html.strip()]
    indice = _indice(presentes)

    cuerpo, n = "", 0
    for aid, tit, html in bloques:
        if html and html.strip():
            n += 1
            cuerpo += _bloque(aid, n, tit, html)

    resumen = _resumen_ejecutivo(panel, dash["pnl"])
    sem = dash.get("semana", {})
    periodo = f"Semana {sem.get('inicio','')} → {sem.get('fin','')} · corte {data['corte']}"

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Informe Financiero — {biz}</title>
<style>{_CSS}</style></head>
<body style="background:#f3f4f6;margin:0;padding:20px 0;">
<div class="wrap" style="max-width:680px;margin:0 auto;">
<div class="head"><h1>Informe Financiero — {biz}</h1>
<div class="sub">{periodo}</div></div>
{resumen}
{indice}
{cuerpo}
<div class="foot">Informe automático · los números no salen a servicios externos salvo los insights IA (texto, sin datos crudos).</div>
</div></body></html>"""
