"""
Dashboard semanal — vertical restaurante.

Reúne Ventas, P&L YTD, Cash Flow, Control de Gastos, Copiloto Tributario,
Conciliación y el cierre de la última semana en un HTML para enviar por correo.
Reutiliza helpers de render, conciliación, control de gastos y economía (IPC)
del vertical hotel (agnósticos).
"""

import logging
from datetime import date, timedelta

from src import config
from src.agents.insights import generar_insights
from src.render import _CSS, _card, _kpis, _fm, _subt, _aviso, renderizar_ipc_html
from src.finanzas.economia import obtener_ipc
from src.finanzas.control_gastos import calcular_control_gastos
from src.finanzas.conciliacion import calcular_conciliacion
from .agents.ventas import calcular_ventas
from .agents.pnl import calcular_pnl
from src.finanzas.pnl import renderizar_pnl_html
from src.finanzas import comercial
from src.marketing.dashboard import calcular_marketing, renderizar_marketing_html
from src.integraciones.sii_dte import estado_dte_dashboard, renderizar_estado_dte_html
from .agents.cash_flow import calcular_cash_flow
from .agents.cierre_diario import calcular_cierre_semanal
from .agents.tributario import calcular_tributario_semanal

logger = logging.getLogger(__name__)


def _semana_cerrada(hoy: date) -> tuple[date, date]:
    corte = hoy - timedelta(days=hoy.weekday() + 1)   # domingo anterior
    desde = corte - timedelta(days=6)                 # lunes de esa semana
    return desde, corte


async def calcular_dashboard() -> dict:
    hoy          = date.today()
    desde, corte = _semana_cerrada(hoy)

    ventas       = await calcular_ventas(desde, corte)
    pnl          = await calcular_pnl(corte)
    cash         = await calcular_cash_flow()
    gastos       = await calcular_control_gastos(desde, corte)
    tributario   = await calcular_tributario_semanal(corte)
    conciliacion = await calcular_conciliacion(corte, 30)
    cierre       = await calcular_cierre_semanal(desde, corte)
    marketing    = await calcular_marketing(corte, 61)
    estado_dte   = await estado_dte_dashboard(corte)

    insights_ventas = await generar_insights("ventas", ventas)
    insights_pnl    = await generar_insights("pnl", pnl)

    ipc = await obtener_ipc(12)

    # Módulo Ventas config-driven (si el tenant tiene bloque `ventas:`); si no, el actual.
    _cfg = config.get_config()
    comercial_html = (await comercial.render(_cfg, "restaurante", desde, corte)
                      if comercial.tiene_config(_cfg) else None)

    return {
        "fecha_envio": str(hoy),
        "semana":      {"inicio": str(desde), "fin": str(corte)},
        "comercial_html": comercial_html,
        "ventas":      ventas,
        "insights_ventas": insights_ventas,
        "pnl":         pnl,
        "insights_pnl": insights_pnl,
        "marketing":   marketing,
        "cash":        cash,
        "gastos":      gastos,
        "tributario":  tributario,
        "conciliacion": conciliacion,
        "estado_dte":  estado_dte,
        "cierre":      cierre,
        "ipc":         ipc,
    }


# ── Secciones ────────────────────────────────────────────────

def _ins(bullets: list[str]) -> str:
    if not bullets:
        return ""
    items = "".join(f'<li>{b}</li>' for b in bullets)
    return (f'<div class="ins"><div class="t">💡 Insights IA</div>'
            f'<ul style="margin:0;padding-left:16px;">{items}</ul></div>')


def _sec_ventas(v: dict, cfg, insights) -> str:
    r = v["resumen"]
    var = r.get("variacion_pct")
    var_txt = f"{var:+.1f}%" if var is not None else "—"
    rows = [
        ("Ventas del período", _fm(r["ventas_total"], cfg)),
        ("vs período anterior", var_txt),
        ("N° pedidos", f"{r['n_pedidos']}"),
        ("Ticket promedio", _fm(r["ticket_promedio"], cfg)),
        ("Margen bruto", f"{_fm(r['margen_bruto'], cfg)} ({r['margen_pct']:.0f}%)"),
        ("Propinas", _fm(r["propinas"], cfg)),
    ]
    filas = ""
    for c in v["por_canal"]:
        filas += (f'<tr><td>{c["canal"]}</td><td>{_fm(c["ventas"], cfg)}</td>'
                  f'<td style="text-align:right;">{c["mix_pct"]:.0f}%</td>'
                  f'<td style="text-align:right;">{_fm(c["ticket"], cfg)}</td></tr>')
    tabla = (f'<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">Por canal</div>'
             f'<table class="dt"><tr><th>Canal</th><th>Ventas</th><th>Mix</th><th>Ticket</th></tr>{filas}</table>')
    top = ""
    if v.get("top_productos"):
        tf = "".join(f'<tr><td>{p["producto"]}</td><td style="text-align:right;">{p["cantidad"]}</td>'
                     f'<td>{_fm(p["ventas"], cfg)}</td></tr>' for p in v["top_productos"])
        top = (f'<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">Top productos</div>'
               f'<table class="dt"><tr><th>Producto</th><th>Cant.</th><th>Ventas</th></tr>{tf}</table>')
    return _card("📊 Ventas", _kpis(rows) + tabla + top + _ins(insights))


def _sec_marketing(m, cfg) -> str:
    if not m:
        return ""   # tenant sin data de marketing → se omite la sección
    return renderizar_marketing_html(m, cfg)


def _sec_estado_dte(d, cfg) -> str:
    if not d:
        return ""   # sin datos de estado DTE → se omite
    return renderizar_estado_dte_html(d, cfg)


def _sec_pnl(p: dict, cfg, insights) -> str:
    return _card("📑 P&L — Estado de Resultados (comparativo YTD)",
                 renderizar_pnl_html(p, cfg) + _ins(insights))


def _sec_cash(c: dict, cfg) -> str:
    r = c["resumen"]
    ico = {"ok": "✅", "alerta": "⚠️", "critico": "🚨"}.get(c["semaforo"], "")
    rows = [
        (f"Liquidez {ico}", c["semaforo"].upper()),
        ("Cobros (28d)", _fm(r["ingresos_28d"], cfg)),
        ("Egresos (28d)", _fm(r["egresos_28d"], cfg)),
        ("Flujo neto semanal", _fm(r["neto_semanal"], cfg)),
        ("Proyección 8 semanas", _fm(r["flujo_proyectado_8sem"], cfg)),
    ]
    return _card("💵 Cash Flow", _kpis(rows))


def _sec_gastos(g: dict, cfg) -> str:
    r = g.get("resumen", {})
    var = r.get("variacion_pct")
    rows = [
        ("Total semana", _fm(r.get("total_actual", 0), cfg)),
        ("Semana anterior", _fm(r.get("total_anterior", 0), cfg)),
        ("Variación", f"{var:+.1f}%" if var is not None else "—"),
        ("Categorías en alerta", f"{len(g.get('alertas', []))}"),
    ]
    filas = ""
    for c in g.get("categorias", [])[:6]:
        filas += (f'<tr><td>{c["categoria"]}</td><td>{_fm(c["monto_actual"], cfg)}</td></tr>')
    tabla = (f'<table class="dt"><tr><th>Categoría</th><th>Monto</th></tr>{filas}</table>') if filas else ""
    return _card("📋 Control de Gastos", _kpis(rows) + tabla)


def _sec_tributario(trib: dict) -> str:
    if not trib or not trib.get("agente_iva"):
        return ""
    iva = trib["agente_iva"]; cum = trib.get("agente_cumplimiento", {}); rie = trib.get("agente_riesgo", {})
    f29 = iva.get("f29", {})
    body = _subt(f"Agente IVA / F29 — período {f29.get('periodo', '')}")
    body += _kpis([
        ("IVA débito", f"${f29.get('iva_debito', 0):,.0f}"),
        ("IVA crédito", f"${f29.get('iva_credito', 0):,.0f}"),
        ("Remanente mes anterior", f"${f29.get('remanente_anterior', 0):,.0f}"),
        ("IVA a pagar", f"${f29.get('iva_a_pagar', 0):,.0f}"),
        (f"PPM ({f29.get('ppm_tasa_pct', 0)}%)", f"${f29.get('ppm', 0):,.0f}"),
        ("Retención honorarios", f"${f29.get('retencion_honorarios', 0):,.0f}"),
        ("TOTAL F29 a pagar", f"${f29.get('total_a_pagar', 0):,.0f}"),
        ("Vence", f"{f29.get('vencimiento', 'N/A')} (en {f29.get('dias_para_vencimiento', 0)}d)"),
    ])
    body += _subt("Agente Cumplimiento — Próximos vencimientos")
    venc = cum.get("proximos_vencimientos", [])
    if venc:
        filas = "".join(f'<tr><td>{x["fecha"]}</td><td>{x["nombre"]}</td>'
                        f'<td style="text-align:right;">{x["dias_restantes"]}d</td></tr>' for x in venc[:6])
        body += f'<table class="dt"><tr><th>Fecha</th><th>Obligación</th><th>Faltan</th></tr>{filas}</table>'
    score = rie.get("score_riesgo", "bajo")
    ico = "🔴" if score == "alto" else "🟠" if score == "medio" else "🟢"
    body += _subt(f"Agente Riesgo — Nivel: {ico} {score}")
    docs = rie.get("documentos_pendientes", {})
    if docs.get("cantidad", 0) > 0:
        body += _aviso("alerta", f"{docs['cantidad']} documento(s) pendiente(s)",
                       f"IVA potencial recuperable: ${docs.get('iva_potencial_recuperable', 0):,.0f}")
    for inc in rie.get("inconsistencias", []):
        body += _aviso(inc.get("nivel", "info"), inc.get("titulo", ""), inc.get("descripcion", ""))
    for al in rie.get("alertas", []):
        body += _aviso(al.get("nivel", "info"), al.get("titulo", ""), al.get("descripcion", ""), al.get("recomendacion", ""))
    if not rie.get("inconsistencias") and not rie.get("alertas"):
        body += '<div style="font-size:12px;color:#047857;margin-top:6px;">Sin inconsistencias ni alertas.</div>'
    return _card("🇨🇱 Copiloto Tributario", body)


def _sec_conciliacion(con: dict) -> str:
    if not con:
        return ""
    if not con.get("tiene_cartola"):
        return _card("🏦 Conciliación bancaria",
                     '<div style="font-size:12px;color:#6b7280;">No hay cartola cargada en el período. '
                     'Sube tu cartola (CSV) para conciliar.</div>')
    r = con["resumen"]
    body = _kpis([
        ("Movimientos", f"{r.get('movimientos', 0)}"),
        ("Conciliados", f"{r.get('conciliados', 0)} ({r.get('pct_conciliado', 0):.0f}%)"),
        ("Monto conciliado", f"${r.get('monto_conciliado', 0):,.0f}"),
        ("Sin respaldo", f"{con.get('sin_respaldo_total', 0)}"),
        ("Libro sin movimiento", f"{con.get('libro_sin_movimiento_total', 0)}"),
    ])
    return _card("🏦 Conciliación bancaria", body)


def _sec_cierre(c: dict, cfg) -> str:
    t = c["totales"]
    filas = ""
    for d in c["por_dia"]:
        filas += (f'<tr><td>{d["fecha"][5:]}</td><td style="text-align:right;">{d["n_pedidos"]}</td>'
                  f'<td>{_fm(d["ventas"], cfg)}</td></tr>')
    tabla = f'<table class="dt"><tr><th>Día</th><th>Pedidos</th><th>Ventas</th></tr>{filas}</table>'
    rows = [
        ("Ventas de la semana", _fm(t["ventas"], cfg)),
        ("Cobrado", _fm(t["cobrado"], cfg)),
        (f"Costo de ventas (food cost {t.get('margen_pct', 0) and round(100 - t['margen_pct'], 1)}%)",
         _fm(t.get("costo_ventas", 0), cfg)),
        (f"Margen bruto ({t.get('margen_pct', 0)}%)", _fm(t.get("margen_bruto", 0), cfg)),
        ("Gastos operativos", _fm(t["gastos"], cfg)),
        (f"Resultado {'✅' if t['resultado_estado'] == 'positivo' else '🔴'}", _fm(t["resultado"], cfg)),
        ("Pedidos / Comensales", f"{t['n_pedidos']} / {t['comensales']}"),
        ("Ticket promedio", _fm(t["ticket_promedio"], cfg)),
    ]
    return _card("🧾 Cierre de la semana", _kpis(rows) + tabla)


def renderizar_dashboard_html(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Restaurante")
    sem = data["semana"]
    body = (
        _sec_ventas(data["ventas"], cfg, data.get("insights_ventas"))
        + _sec_pnl(data["pnl"], cfg, data.get("insights_pnl"))
        + _sec_cash(data["cash"], cfg)
        + _sec_gastos(data["gastos"], cfg)
        + _sec_tributario(data.get("tributario", {}))
        + _sec_conciliacion(data.get("conciliacion", {}))
        + _sec_estado_dte(data.get("estado_dte"), cfg)
        + _sec_cierre(data["cierre"], cfg)
        + _sec_marketing(data.get("marketing"), cfg)
        + renderizar_ipc_html(data.get("ipc"))
    )
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard semanal — {biz}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<div class="head"><h1>📈 Dashboard Semanal — {biz}</h1>
<div class="sub">Semana {sem['inicio']} → {sem['fin']} · generado {data['fecha_envio']}</div></div>
{body}
<div class="foot">Reporte automático · los números no salen a servicios externos salvo los insights IA.</div>
</div></body></html>"""


def secciones_html(data: dict, cfg: dict) -> dict:
    """Secciones del dashboard renderizadas, con ids canónicos, para que el
    Informe Financiero horizontal las ensamble en su orden top-down."""
    return {
        "pnl":         _sec_pnl(data["pnl"], cfg, data.get("insights_pnl")),
        "comercial":   data.get("comercial_html") or _sec_ventas(data["ventas"], cfg, data.get("insights_ventas")),
        "gastos":      _sec_gastos(data["gastos"], cfg),
        "tributario":  _sec_tributario(data.get("tributario", {})),
        "conciliacion": _sec_conciliacion(data.get("conciliacion", {})),
        "estado_dte":  _sec_estado_dte(data.get("estado_dte"), cfg),
        "cierre":      _sec_cierre(data["cierre"], cfg),
        "marketing":   _sec_marketing(data.get("marketing"), cfg),
        "ipc":         renderizar_ipc_html(data.get("ipc")),
    }
