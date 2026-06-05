"""
Dashboard semanal — consolida los reportes financieros en un único HTML
diseñado para enviarse por email los lunes.

Orden por importancia (problemas primero):
  1. Puntos de atención (derivados de los semáforos de cada reporte)
  2. P&L YTD            (con insights IA)
  3. Cash Flow
  4. Rentabilidad canal (con insights IA)
  5. Revenue Management
  6. Control de Gastos
  7. Copiloto Tributario (IVA, recomendaciones, alertas)
  8. Cierre de la semana
  9. Contexto económico (Inflación Chile)
"""

import logging
from datetime import date, timedelta

from ... import config
from src.finanzas.economia import obtener_ipc
from ...agents._common import var_txt
from src.render import _CSS, _fm, _kpis, _card, _subt, _aviso, renderizar_ipc_html
from .agents.cash_flow import calcular_cash_flow
from .agents.cierre_diario import calcular_cierre_semanal
from src.finanzas.control_gastos import calcular_control_gastos, calcular_gastos_analitico
from .agents.tributario import calcular_tributario_semanal
from src.finanzas.conciliacion import calcular_conciliacion
from ...agents.insights import generar_insights
from .agents.pnl import calcular_pnl
from src.finanzas.pnl import renderizar_pnl_html
from .agents.rentabilidad_canal import calcular_rentabilidad_canal
from .agents.revenue_management import calcular_revenue_management

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Cálculo consolidado
# ─────────────────────────────────────────────────────────────

def _semana_cerrada(hoy: date) -> tuple[date, date]:
    """Última semana completa lunes→domingo respecto a `hoy`."""
    corte = hoy - timedelta(days=hoy.weekday() + 1)  # domingo anterior
    desde = corte - timedelta(days=6)                # lunes de esa semana
    return desde, corte


async def calcular_dashboard() -> dict:
    hoy           = date.today()
    desde, corte  = _semana_cerrada(hoy)

    pnl     = await calcular_pnl(corte)
    rent    = await calcular_rentabilidad_canal(corte.year, corte.month, hasta=corte)
    cierre  = await calcular_cierre_semanal(desde, corte)
    revenue = await calcular_revenue_management()
    cash    = await calcular_cash_flow()
    gastos  = await calcular_control_gastos(desde, corte)
    tributario = await calcular_tributario_semanal(corte)
    conciliacion = await calcular_conciliacion(corte, 30)

    # Insights IA solo para los dos reportes estratégicos
    insights_pnl  = await generar_insights("pnl", pnl)
    insights_rent = await generar_insights("rentabilidad_canal", rent)

    # Contexto económico (IPC Chile) — None si la fuente no responde
    ipc = await obtener_ipc(12)
    ipc_acum = ipc["acumulado_pct"] if ipc else None

    # Vista analítica de gastos (12m) — gasto vs inflación, tendencia, proveedores
    gastos_analitico = await calcular_gastos_analitico(corte, ipc_acum)

    problemas = _detectar_problemas(pnl, cash, gastos, rent, cierre)

    return {
        "fecha_envio": str(hoy),
        "semana":      {"inicio": str(desde), "fin": str(corte)},
        "problemas":   problemas,
        "pnl":         pnl,
        "insights_pnl": insights_pnl,
        "cash":        cash,
        "rent":        rent,
        "insights_rent": insights_rent,
        "revenue":     revenue,
        "gastos":      gastos,
        "gastos_analitico": gastos_analitico,
        "tributario":  tributario,
        "conciliacion": conciliacion,
        "cierre":      cierre,
        "ipc":         ipc,
    }


def _detectar_problemas(pnl, cash, gastos, rent, cierre) -> list[dict]:
    """Deriva los puntos de atención de los semáforos/estados de cada reporte."""
    problemas: list[dict] = []

    # Cash flow: liquidez en alerta o crítica
    sem = cash.get("semaforo")
    if sem == "critico":
        problemas.append({"nivel": "critico", "origen": "Cash Flow",
                          "texto": "Liquidez en estado crítico: el flujo acumulado proyectado se vuelve negativo."})
    elif sem == "alerta":
        problemas.append({"nivel": "alerta", "origen": "Cash Flow",
                          "texto": "Liquidez ajustada: la cobertura mínima cae por debajo del umbral."})

    # P&L YTD: resultado neto negativo
    if pnl["resumen"]["resultado_neto"] < 0:
        problemas.append({"nivel": "critico", "origen": "P&L YTD",
                          "texto": "El resultado neto acumulado del año es negativo."})

    # Cierre de la semana: resultado negativo
    if cierre["totales"]["gop_estado"] == "negativo":
        problemas.append({"nivel": "alerta", "origen": "Cierre semanal",
                          "texto": "El GOP devengado de la última semana fue negativo."})

    # Control de gastos: categorías con variación crítica
    for a in gastos.get("alertas", []):
        if a["nivel"] == "critico":
            problemas.append({"nivel": "alerta", "origen": "Control de Gastos",
                              "texto": f"Gasto en «{a['categoria']}» subió {var_txt(a['variacion_pct'])} vs período anterior."})

    # Rentabilidad: cancelación global alta
    tasa = rent["totales"].get("tasa_cancel_pct", 0)
    if tasa >= 20:
        problemas.append({"nivel": "alerta", "origen": "Rentabilidad",
                          "texto": f"Tasa de cancelación global elevada: {tasa:.1f}%."})

    # Orden: críticos primero
    problemas.sort(key=lambda p: 0 if p["nivel"] == "critico" else 1)
    return problemas


# ─────────────────────────────────────────────────────────────
# Render HTML
# ─────────────────────────────────────────────────────────────

def _insights_block(insights: list[str]) -> str:
    if not insights:
        return ""
    lis = "".join(f"<li>{i}</li>" for i in insights)
    return f'<div class="ins"><div class="t">💡 Insights IA</div><ul style="margin:0;padding-left:16px;">{lis}</ul></div>'


def _sec_atencion(problemas: list[dict]) -> str:
    if not problemas:
        return ('<div class="attn ok"><h2>✅ Puntos de atención — sin alertas</h2></div>')
    lis = ""
    for p in problemas:
        tag = "c" if p["nivel"] == "critico" else "a"
        lab = "CRÍTICO" if p["nivel"] == "critico" else "ATENCIÓN"
        lis += f'<li><span class="tag {tag}">{lab}</span><b>{p["origen"]}:</b> {p["texto"]}</li>'
    return f'<div class="attn bad"><h2>🚨 Puntos de atención</h2><ul>{lis}</ul></div>'


def _sec_pnl(pnl: dict, insights: list[str], cfg) -> str:
    tabla = renderizar_pnl_html(pnl, cfg)
    return _card("📑 P&L — Estado de Resultados (comparativo YTD)",
                 tabla + _insights_block(insights))


def _sec_cash(cash: dict, cfg) -> str:
    r   = cash["resumen"]
    sem = cash["semaforo"]
    ico = {"ok": "✅", "alerta": "⚠️", "critico": "🚨"}.get(sem, "")
    cob = (f"{r['semanas_cobertura']:.1f} semanas" if r["semanas_cobertura"] is not None else "—")
    rows = [
        (f"Liquidez {ico}",        sem.upper()),
        ("Cobertura mínima",       cob),
        ("Flujo neto proy. (8 sem)", _fm(r["flujo_neto_proyectado"], cfg)),
        ("Cobros pendientes",      _fm(r["cobros_pendientes"], cfg)),
        ("Vence en 14 días",       _fm(r["pendiente_vence_14d"], cfg)),
    ]
    return _card("💵 Cash Flow", _kpis(rows))


def _sec_rent(rent: dict, insights: list[str], cfg) -> str:
    t = rent["totales"]
    filas = ""
    for c in rent["canales"][:6]:
        if c["ingresos_netos"] == 0 and c["total_reservas"] == 0:
            continue
        filas += (f'<tr><td>{c["canal"]}</td><td>{_fm(c["ingresos_netos"], cfg)}</td>'
                  f'<td>{c["mix_pct"]:.0f}%</td><td>{c["tasa_cancel_pct"]:.1f}%</td></tr>')
    tabla = (f'<table class="dt"><tr><th>Canal</th><th>Neto</th><th>Mix</th><th>Cancel.</th></tr>{filas}</table>')
    rows = [
        ("Ingresos netos (mes)",   _fm(t["ingresos_netos"], cfg)),
        ("Comisiones OTA",         _fm(t["comisiones"], cfg)),
        ("Cancelación global",     f"{t['tasa_cancel_pct']:.1f}%"),
        ("Canal más rentable",     rent["insights"]["canal_mas_rentable"] or "—"),
    ]
    body = _kpis(rows) + tabla + _insights_block(insights)
    return _card(f"🏪 Rentabilidad por Canal — {rent['mes_nombre']}", body)


def _sec_revenue(rev: dict, cfg) -> str:
    s   = rev["snapshot"]
    h7  = rev["historico"]["7d"]
    h30 = rev["historico"]["30d"]
    rows = [
        ("Ocupación (últimos 7d)", f"{h7['ocupacion_pct']:.1f}%"),
        ("ADR (últimos 7d)",       _fm(h7["adr"], cfg)),
        ("RevPAR (últimos 7d)",    _fm(h7["revpar"], cfg)),
        ("ADR (últimos 30d)",      _fm(h30["adr"], cfg)),
        ("RevPAR (últimos 30d)",   _fm(h30["revpar"], cfg)),
    ]
    return _card("📊 Revenue Management", _kpis(rows))


def _sec_gastos(g: dict, cfg, ana: dict | None = None) -> str:
    r = g["resumen"]
    var = var_txt(r.get("variacion_pct"))
    rows = [
        ("Total semana",         _fm(r["total_actual"], cfg)),
        ("Semana anterior",      _fm(r["total_anterior"], cfg)),
        ("Variación",            var),
        ("Categorías en alerta", str(len(g.get("alertas", [])))),
        ("Sin clasificar",       str(g.get("sin_categoria", {}).get("n", 0))),
    ]
    body = _kpis(rows)

    if ana:
        # Vista CFO: gasto vs inflación
        cfo_rows = [("Gasto promedio mensual (12m)", _fm(ana["gasto_prom_mensual"], cfg))]
        if ana["crecimiento_pct"] is not None:
            cfo_rows.append(("Crecimiento del gasto (12m)", var_txt(ana["crecimiento_pct"])))
        if ana["ipc_acum_pct"] is not None:
            cfo_rows.append(("Inflación mensual (Banco Central)", f"{ana['ipc_acum_pct']:+.1f}%"))
        if ana["brecha_pp"] is not None:
            bp = ana["brecha_pp"]
            cls = "neg" if bp > 0 else "pos"
            signo = "por encima" if bp > 0 else "por debajo"
            cfo_rows.append(("Gasto vs inflación",
                             f'<span class="{cls}">{abs(bp):.1f} pp {signo}</span>'))
        body += ('<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">'
                 'Vista CFO — costos vs inflación</div>' + _kpis(cfo_rows))

        # Gasto por categoría (12m): crecimiento y comparación vs IPC
        if ana["top_categorias"]:
            filas = ""
            for c in ana["top_categorias"]:
                crec = var_txt(c["crecimiento_pct"]) if c["crecimiento_pct"] is not None else "—"
                vp = c["vs_ipc_pp"]
                if vp is None:
                    vsipc = "—"
                elif vp > 0:
                    vsipc = f'<span class="neg">+{vp:.1f}%</span>'
                else:
                    vsipc = f'<span class="pos">{vp:.1f}%</span>'
                filas += (f'<tr><td>{c["categoria"]}</td><td>{_fm(c["monto"], cfg)}</td>'
                          f'<td>{c["pct"]:.0f}%</td><td>{crec}</td><td>{vsipc}</td></tr>')
            ipc_ref = (f' · Inflación mensual: {ana["ipc_acum_pct"]:+.1f}%'
                       if ana.get("ipc_acum_pct") is not None else "")
            body += ('<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">'
                     f'Gasto por categoría (12m){ipc_ref}</div>'
                     '<table class="dt"><tr><th>Categoría</th><th>Monto</th><th>%</th>'
                     '<th>Crec. 12m</th><th>vs Inflación</th></tr>'
                     f'{filas}</table>')

        # Top proveedores (12m)
        if ana["top_proveedores"]:
            filas = "".join(
                f'<tr><td>{p["proveedor"]}</td><td>{_fm(p["monto"], cfg)}</td><td>{p["n"]}</td></tr>'
                for p in ana["top_proveedores"]
            )
            body += ('<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">'
                     'Top proveedores (12m)</div>'
                     f'<table class="dt"><tr><th>Proveedor</th><th>Monto</th><th>N° gastos</th></tr>{filas}</table>')

    return _card("📋 Control de Gastos", body)


def _sec_tributario(trib: dict) -> str:
    """Copiloto Tributario: agentes IVA, Cumplimiento y Riesgo en una tarjeta."""
    if not trib or not trib.get("agente_iva"):
        return ""

    iva = trib.get("agente_iva", {})
    cum = trib.get("agente_cumplimiento", {})
    rie = trib.get("agente_riesgo", {})

    # ── Agente IVA / F29 ───────────────────────────────────────────────
    f29 = iva.get("f29", {})
    body = _subt(f"Agente IVA / F29 — período {f29.get('periodo', '')}")
    body += _kpis([
        ("IVA débito",             f"${f29.get('iva_debito', 0):,.0f}"),
        ("IVA crédito",            f"${f29.get('iva_credito', 0):,.0f}"),
        ("Remanente mes anterior", f"${f29.get('remanente_anterior', 0):,.0f}"),
        ("IVA a pagar",            f"${f29.get('iva_a_pagar', 0):,.0f}"),
        (f"PPM ({f29.get('ppm_tasa_pct', 0)}%)", f"${f29.get('ppm', 0):,.0f}"),
        ("Retención honorarios",   f"${f29.get('retencion_honorarios', 0):,.0f}"),
        ("TOTAL F29 a pagar",      f"${f29.get('total_a_pagar', 0):,.0f}"),
        ("Vence", f"{f29.get('vencimiento', 'N/A')} (en {f29.get('dias_para_vencimiento', 0)}d)"),
    ])
    if f29.get("iva_postergado"):
        body += (f'<div style="margin:8px 0;padding:8px;background:#eff6ff;'
                 f'border-left:3px solid #3b82f6;border-radius:4px;font-size:12px;color:#1e40af;">'
                 f'IVA postergado: el IVA a pagar (${f29.get("iva_a_pagar", 0):,.0f}) vence '
                 f'{f29.get("vencimiento_iva", "N/A")}. A pagar ahora (PPM + retenciones): '
                 f'<b>${f29.get("total_a_pagar_ahora", 0):,.0f}</b>.</div>')

    # ── Agente Cumplimiento ────────────────────────────────────────────
    body += _subt("Agente Cumplimiento — Próximos vencimientos")
    venc = cum.get("proximos_vencimientos", [])
    if venc:
        filas = ""
        for v in venc[:8]:
            filas += (f'<tr><td>{v["fecha"]}</td><td>{v["nombre"]}</td>'
                      f'<td style="text-align:right;">{v["dias_restantes"]}d</td></tr>')
        body += (f'<table class="dt"><tr><th>Fecha</th><th>Obligación</th><th>Faltan</th></tr>'
                 f'{filas}</table>')
    else:
        body += ('<div style="font-size:12px;color:#6b7280;">Sin vencimientos en los próximos '
                 f'{cum.get("horizonte_dias", 60)} días.</div>')

    # ── Agente Riesgo ──────────────────────────────────────────────────
    score = rie.get("score_riesgo", "bajo")
    score_ico = "🔴" if score == "alto" else "🟠" if score == "medio" else "🟢"
    body += _subt(f"Agente Riesgo — Nivel: {score_ico} {score}")

    docs = rie.get("documentos_pendientes", {})
    if docs.get("cantidad", 0) > 0:
        body += (f'<div style="margin:8px 0;padding:10px;background:#fef3c7;'
                 f'border-left:3px solid #f59e0b;border-radius:4px;">'
                 f'<div style="font-weight:600;font-size:13px;color:#92400e;">'
                 f'📋 {docs["cantidad"]} documento(s) pendiente(s)</div>'
                 f'<div style="font-size:12px;color:#78350f;margin-top:3px;">'
                 f'IVA potencial recuperable: <b>${docs.get("iva_potencial_recuperable", 0):,.0f}</b>'
                 f'</div></div>')

    for inc in rie.get("inconsistencias", []):
        body += _aviso(inc.get("nivel", "info"), inc.get("titulo", ""), inc.get("descripcion", ""))
    for al in rie.get("alertas", []):
        body += _aviso(al.get("nivel", "info"), al.get("titulo", ""),
                       al.get("descripcion", ""), al.get("recomendacion", ""))

    if not rie.get("inconsistencias") and not rie.get("alertas"):
        body += ('<div style="font-size:12px;color:#047857;margin-top:6px;">'
                 'Sin inconsistencias ni alertas detectadas.</div>')

    return _card("🇨🇱 Copiloto Tributario", body)


def _sec_conciliacion(con: dict) -> str:
    """Conciliación bancaria: cartola vs pagos/gastos/facturas."""
    if not con:
        return ""

    if not con.get("tiene_cartola"):
        body = ('<div style="font-size:12px;color:#6b7280;">'
                'No hay cartola cargada en el período. Sube tu cartola del banco (CSV) '
                'para conciliar automáticamente contra pagos, gastos y facturas.</div>')
        return _card("🏦 Conciliación bancaria", body)

    r = con.get("resumen", {})
    pct = r.get("pct_conciliado", 0)
    body = _kpis([
        ("Movimientos", f"{r.get('movimientos', 0)}"),
        ("Conciliados", f"{r.get('conciliados', 0)} ({pct:.0f}%)"),
        ("Monto conciliado", f"${r.get('monto_conciliado', 0):,.0f}"),
        ("Movimientos sin respaldo", f"{con.get('sin_respaldo_total', 0)}"),
        ("Registros de libro sin movimiento", f"{con.get('libro_sin_movimiento_total', 0)}"),
    ])

    sr = con.get("sin_respaldo", [])
    if sr:
        filas = ""
        for m in sr:
            filas += (f'<tr><td>{m["fecha"][5:]}</td>'
                      f'<td style="text-align:right;">${m["monto"]:,.0f}</td>'
                      f'<td>{m["glosa"][:40]}</td></tr>')
        total = con.get("sin_respaldo_total", len(sr))
        body += (f'<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">'
                 f'Movimientos sin respaldo ({total})</div>'
                 f'<table class="dt"><tr><th>Fecha</th><th>Monto</th><th>Glosa</th></tr>'
                 f'{filas}</table>')
    else:
        body += ('<div style="font-size:12px;color:#047857;margin-top:6px;">'
                 'Todos los movimientos tienen respaldo.</div>')

    return _card("🏦 Conciliación bancaria", body)


def _sec_cierre(c: dict, cfg) -> str:
    t = c["totales"]
    m = c["movimientos"]
    filas = ""
    for d in c["por_dia"]:
        cls = "pos" if d["gop_devengado"] >= 0 else "neg"
        filas += (f'<tr><td>{d["fecha"][5:]}</td><td>{d["ocupacion_pct"]:.0f}%</td>'
                  f'<td>{_fm(d["ingresos"], cfg)}</td>'
                  f'<td class="{cls}">{_fm(d["gop_devengado"], cfg)}</td></tr>')
    tabla = (f'<table class="dt"><tr><th>Día</th><th>Ocup.</th><th>Ingresos</th><th>GOP</th></tr>{filas}</table>')
    rows = [
        ("Ingresos de la semana", _fm(t["ingresos"], cfg)),
        ("Cobrado",               _fm(t["cobrado"], cfg)),
        ("Gastos",                _fm(t["gastos"], cfg)),
        (f"GOP devengado {'✅' if t['gop_estado']=='positivo' else '🔴'}", _fm(t["gop_devengado"], cfg)),
        ("Ocupación promedio",    f"{c['ocupacion_promedio_pct']:.1f}%"),
        ("Check-ins / Check-outs", f"{m['checkins']} / {m['checkouts']}"),
    ]
    return _card("🧾 Cierre de la semana", _kpis(rows) + tabla)


def renderizar_dashboard_html(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    sem = data["semana"]
    body = (
        _sec_atencion(data["problemas"])
        + _sec_pnl(data["pnl"], data["insights_pnl"], cfg)
        + _sec_cash(data["cash"], cfg)
        + _sec_rent(data["rent"], data["insights_rent"], cfg)
        + _sec_revenue(data["revenue"], cfg)
        + _sec_gastos(data["gastos"], cfg, data.get("gastos_analitico"))
        + _sec_tributario(data.get("tributario", {}))
        + _sec_conciliacion(data.get("conciliacion", {}))
        + _sec_cierre(data["cierre"], cfg)
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
<div class="foot">Reporte automático · los números no salen a servicios externos salvo los insights IA (texto, sin datos crudos).</div>
</div></body></html>"""
