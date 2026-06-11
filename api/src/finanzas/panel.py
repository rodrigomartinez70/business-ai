"""
Panel Financiero (horizontal) — junta los agentes de gestión financiera en un
único informe/correo: CFO Virtual, Tesorería, Cuentas por Cobrar, Cuentas por
Pagar y Presupuesto. No calcula nada propio: orquesta y renderiza.
"""

import logging
from datetime import date

from src.finanzas.cfo import calcular_cfo
from src.finanzas.tesoreria import calcular_tesoreria
from src.finanzas.cuentas_por_cobrar import calcular_cuentas_por_cobrar
from src.finanzas.cuentas_por_pagar import calcular_cuentas_por_pagar
from src.finanzas.presupuesto import calcular_presupuesto

logger = logging.getLogger(__name__)

_COLOR = {"ok": "#16a34a", "alerta": "#d97706", "critico": "#dc2626",
          "info": "#2563eb"}


async def calcular_panel(hasta: date) -> dict:
    return {
        "corte": str(hasta),
        "cfo": await calcular_cfo(hasta),
        "tesoreria": await calcular_tesoreria(hasta),
        "cuentas_por_cobrar": await calcular_cuentas_por_cobrar(hasta),
        "cuentas_por_pagar": await calcular_cuentas_por_pagar(hasta),
        "presupuesto": await calcular_presupuesto(hasta),
    }


# ─────────────────────────────────────────────────────────────
# Render HTML (email-safe: estilos inline, sin emojis)
# ─────────────────────────────────────────────────────────────

def _m(v) -> str:
    try:
        neg = float(v) < 0
    except (TypeError, ValueError):
        return "—"
    s = f"-${abs(v):,.0f}" if neg else f"${v:,.0f}"
    return f'<span style="color:#dc2626;">{s}</span>' if neg else s


def _pct_color(v) -> str:
    """Porcentaje con signo; los negativos en rojo."""
    if v is None:
        return "s/d"
    s = f"{v:+.0f}%"
    return f'<span style="color:#dc2626;">{s}</span>' if v < 0 else s


def _badge(estado: str) -> str:
    c = _COLOR.get(estado, "#6b7280")
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
            f'background:{c};color:#fff;font-size:12px;font-weight:600;'
            f'text-transform:uppercase;">{estado}</span>')


def _card(titulo: str, cuerpo: str) -> str:
    return (f'<div style="background:#fff;border:1px solid #e5e7eb;border-radius:10px;'
            f'padding:18px 20px;margin:0 0 16px;">'
            f'<h2 style="margin:0 0 12px;font-size:17px;color:#111827;">{titulo}</h2>'
            f'{cuerpo}</div>')


def _kv(label: str, valor: str) -> str:
    return (f'<tr><td style="padding:4px 12px 4px 0;color:#6b7280;font-size:13px;">{label}</td>'
            f'<td style="padding:4px 0;color:#111827;font-size:14px;font-weight:600;'
            f'text-align:right;">{valor}</td></tr>')


def _tabla(headers: list[str], filas: list[list[str]]) -> str:
    if not filas:
        return '<p style="color:#9ca3af;font-size:13px;margin:6px 0;">Sin registros.</p>'
    th = "".join(f'<th style="text-align:left;padding:6px 10px;background:#f9fafb;'
                 f'border-bottom:1px solid #e5e7eb;font-size:12px;color:#6b7280;">{h}</th>'
                 for h in headers)
    rows = ""
    for f in filas:
        tds = "".join(f'<td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;'
                      f'font-size:13px;color:#374151;">{c}</td>' for c in f)
        rows += f"<tr>{tds}</tr>"
    return (f'<table style="width:100%;border-collapse:collapse;margin:8px 0 0;">'
            f'<thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>')


def _sec_cfo(d: dict) -> str:
    ind = d["indicadores"]
    rent = ind.get("rentabilidad") or {}
    liq = ind["liquidez"]
    rows = "<table>"
    if rent:
        rows += _kv("Margen bruto", f"{rent.get('margen_bruto_pct', 0):.0f}%")
        rows += _kv("Resultado neto", _m(rent.get("resultado_neto")))
    if liq.get("caja_estimada") is not None:
        rows += _kv("Caja estimada", _m(liq["caja_estimada"]))
        rows += _kv("Caja proyectada (8 sem)", _m(liq.get("caja_proyectada_8sem")))
    rows += _kv("Por cobrar", _m(ind["por_cobrar"].get("total")))
    rows += _kv("Por pagar", _m(ind["por_pagar"].get("total")))
    if ind["tributario"].get("riesgo"):
        rows += _kv("Riesgo tributario", ind["tributario"]["riesgo"])
    rows += "</table>"

    puntos = d.get("puntos_clave", [])
    if puntos:
        lis = "".join(
            f'<li style="margin:4px 0;color:#374151;font-size:13px;">'
            f'<span style="color:{_COLOR.get(p["nivel"], "#6b7280")};font-weight:700;">&#9679;</span> '
            f'{p["texto"]}</li>' for p in puntos)
        puntos_html = f'<ul style="margin:10px 0 0;padding-left:4px;list-style:none;">{lis}</ul>'
    else:
        puntos_html = ('<p style="color:#16a34a;font-size:13px;margin:10px 0 0;">'
                       'Sin alertas: indicadores dentro de lo esperado.</p>')

    titulo = f'CFO Virtual &mdash; Resumen Ejecutivo &nbsp; {_badge(d["semaforo"])}'
    return _card(titulo, rows + puntos_html)


def _sec_tesoreria(d: dict) -> str:
    f = d["flujo_semanal"]
    rows = ("<table>"
            + _kv("Liquidez", _badge(d["semaforo"]))
            + _kv("Caja estimada", f'{_m(d["caja_estimada"])} <span style="color:#9ca3af;font-weight:400;">({d["fuente_caja"]})</span>')
            + _kv("Cobros / semana", _m(f["cobros"]))
            + _kv("Egresos / semana", _m(f["egresos"]))
            + _kv("Flujo neto / semana", _m(f["neto"]))
            + _kv("Caja proyectada (8 sem)", _m(d["caja_proyectada_8sem"]))
            + "</table>")
    prop = [[p["vence"], p["proveedor"], _m(p["monto"]),
             ("Pagar" if p["accion"] == "pagar" else "Postergar")]
            for p in d.get("propuesta_pagos", [])]
    cuerpo = rows + ('<h3 style="font-size:14px;color:#374151;margin:14px 0 0;">Propuesta de pagos</h3>'
                     + _tabla(["Vence", "Proveedor", "Monto", "Acción"], prop))
    return _card("Tesorería", cuerpo)


def _sec_cxc(d: dict) -> str:
    a = d["aging"]
    rows = ("<table>"
            + _kv("Total por cobrar", _m(d["total_por_cobrar"]))
            + _kv("DSO", f'{d["dso"]:.0f} días' if d.get("dso") is not None else "s/d")
            + _kv("Por vencer (0&ndash;30 días)", _m(a["d0_30"]))
            + _kv("31&ndash;60 días", _m(a["d31_60"]))
            + _kv("+60 días", _m(a["d60_mas"]))
            + "</table>")
    det = [[x["fecha"], x["cliente"], _m(x["monto"]), f'{x["dias"]}d'] for x in d.get("detalle", [])]
    cuerpo = rows + _tabla(["Fecha", "Cliente", "Monto", "Antigüedad"], det)
    return _card("Cuentas por Cobrar", cuerpo)


def _sec_cxp(d: dict) -> str:
    a = d["aging"]
    rows = ("<table>"
            + _kv("Total por pagar", _m(d["total_por_pagar"]))
            + _kv("Vencido", _m(d["vencido"]))
            + _kv("Por vencer", _m(a["por_vencer"]))
            + _kv("Vencido 1&ndash;30 días", _m(a["d1_30"]))
            + _kv("Vencido 31&ndash;60 días", _m(a["d31_60"]))
            + _kv("Vencido +60 días", _m(a["d60_mas"]))
            + "</table>")
    venc = [[x["vence"], x["proveedor"], _m(x["monto"]), f'{x["dias"]}d'] for x in d.get("vencidas", [])]
    prox = [[x["vence"], x["proveedor"], _m(x["monto"])] for x in d.get("proximos_vencimientos", [])]
    cuerpo = (rows
              + '<h3 style="font-size:14px;color:#374151;margin:14px 0 0;">Vencidas</h3>'
              + _tabla(["Vence", "Proveedor", "Monto", "Atraso"], venc)
              + '<h3 style="font-size:14px;color:#374151;margin:14px 0 0;">Próximos vencimientos</h3>'
              + _tabla(["Vence", "Proveedor", "Monto"], prox))
    return _card("Cuentas por Pagar", cuerpo)


def _sec_presupuesto(d: dict) -> str:
    if not d.get("tiene_presupuesto"):
        return _card("Presupuesto",
                     '<p style="color:#9ca3af;font-size:13px;margin:0;">No hay presupuesto '
                     f'cargado para {d.get("anio")}.</p>')
    ing, gas = d["ingresos"], d["gastos"]

    def _kpi(label, real, presup, var_pct):
        return (
            '<td width="50%" style="padding:6px;">'
            '<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;">'
            f'<div style="font-size:11px;color:#6b7280;text-transform:uppercase;letter-spacing:.4px;">{label}</div>'
            f'<div style="font-size:18px;font-weight:700;color:#111827;margin-top:3px;">{_m(real)} '
            f'<span style="font-size:13px;font-weight:600;">({_pct_color(var_pct)})</span></div>'
            f'<div style="font-size:11px;color:#6b7280;margin-top:2px;">presup. {_m(presup)}</div>'
            '</div></td>')

    kpis = (
        '<table width="100%" style="border-collapse:collapse;margin:0 0 4px;"><tr>'
        + _kpi("Ingresos", ing["real"], ing["presupuesto"], ing["var_pct"])
        + _kpi("Gastos",   gas["real"], gas["presupuesto"], gas["var_pct"])
        + '</tr></table>')

    desv = [[x["categoria"], _m(x["real"]), _m(x["presupuesto"]), _pct_color(x["var_pct"]),
             ("Favorable" if x.get("favorable") else "Atención")]
            for x in d.get("desviaciones", [])]
    cuerpo = (kpis + '<h3 style="font-size:14px;color:#374151;margin:14px 0 0;">Desviaciones</h3>'
              + _tabla(["Categoría", "Real", "Presup.", "Var.", "Estado"], desv))
    return _card("Control Presupuestario (YTD)", cuerpo)


def renderizar_panel_html(panel: dict, cfg: dict, biz: str) -> str:
    secciones = (
        _sec_cfo(panel["cfo"])
        + _sec_tesoreria(panel["tesoreria"])
        + _sec_cxc(panel["cuentas_por_cobrar"])
        + _sec_cxp(panel["cuentas_por_pagar"])
        + _sec_presupuesto(panel["presupuesto"])
    )
    return (
        f'<div style="background:#f3f4f6;padding:24px;font-family:-apple-system,'
        f'Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        f'<div style="max-width:680px;margin:0 auto;">'
        f'<div style="margin:0 0 18px;">'
        f'<h1 style="margin:0;font-size:22px;color:#111827;">Panel Financiero</h1>'
        f'<p style="margin:4px 0 0;color:#6b7280;font-size:14px;">{biz} &middot; corte {panel["corte"]}</p>'
        f'</div>{secciones}'
        f'<p style="color:#9ca3af;font-size:11px;text-align:center;margin:18px 0 0;">'
        f'Agentes financieros (CFO, Tesorería, CxC, CxP, Presupuesto) &middot; majorbi</p>'
        f'</div></div>'
    )
