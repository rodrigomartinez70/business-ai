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
  7. Cierre de la semana
"""

import logging
from datetime import date, timedelta

from . import config
from .economia import obtener_ipc
from .agents._common import COLOR, fmt_moneda, var_txt
from .agents.cash_flow import calcular_cash_flow
from .agents.cierre_diario import calcular_cierre_semanal
from .agents.control_gastos import calcular_control_gastos, calcular_gastos_analitico
from .agents.insights import generar_insights
from .agents.pnl_mensual import calcular_pnl_ytd
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

    pnl     = await calcular_pnl_ytd(corte)
    rent    = await calcular_rentabilidad_canal(corte.year, corte.month, hasta=corte)
    cierre  = await calcular_cierre_semanal(desde, corte)
    revenue = await calcular_revenue_management()
    cash    = await calcular_cash_flow()
    gastos  = await calcular_control_gastos(desde, corte)

    # Insights IA solo para los dos reportes estratégicos
    insights_pnl  = await generar_insights("pnl_mensual", pnl)
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

    # P&L YTD: GOP negativo
    if pnl["actual"]["resultado"]["estado"] == "negativo":
        problemas.append({"nivel": "critico", "origen": "P&L YTD",
                          "texto": "El resultado operativo (GOP) acumulado del año es negativo."})

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

_CSS = """
body{margin:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1a1a1a;}
.wrap{max-width:760px;margin:0 auto;padding:24px 16px;}
.head{text-align:center;padding:8px 0 20px;}
.head h1{margin:0;font-size:22px;}
.head .sub{color:#6b7280;font-size:13px;margin-top:4px;}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;margin:0 0 16px;overflow:hidden;}
.card>h2{margin:0;padding:12px 16px;font-size:15px;background:#1f2937;color:#fff;}
.card .body{padding:14px 16px;}
.kpis{width:100%;border-collapse:collapse;}
.kpis td{padding:6px 8px;font-size:13px;border-bottom:1px solid #f0f0f0;vertical-align:top;}
.kpis td.k{color:#6b7280;width:55%;}
.kpis td.v{text-align:right;font-weight:600;}
.attn{border-radius:10px;padding:4px 0;margin:0 0 16px;}
.attn.ok{background:#ecfdf5;border:1px solid #a7f3d0;}
.attn.bad{background:#fef2f2;border:1px solid #fecaca;}
.attn h2{margin:0;padding:12px 16px;font-size:15px;}
.attn.ok h2{color:#047857;}
.attn.bad h2{color:#b91c1c;}
.attn ul{margin:0;padding:4px 16px 12px 34px;}
.attn li{font-size:13px;margin:4px 0;}
.tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px;color:#fff;margin-right:6px;}
.tag.c{background:#dc2626;} .tag.a{background:#f59e0b;}
.ins{background:#eef2ff;border-left:3px solid #6366f1;border-radius:4px;padding:8px 12px;margin-top:10px;}
.ins .t{font-size:12px;font-weight:700;color:#4338ca;margin-bottom:4px;}
.ins li{font-size:12px;margin:3px 0;color:#3730a3;}
table.dt{width:100%;border-collapse:collapse;margin-top:8px;}
table.dt th,table.dt td{font-size:12px;padding:4px 6px;border-bottom:1px solid #eee;text-align:right;}
table.dt th:first-child,table.dt td:first-child{text-align:left;}
table.dt th{color:#6b7280;font-weight:600;}
.pos{color:#047857;} .neg{color:#b91c1c;}
.foot{text-align:center;color:#9ca3af;font-size:11px;padding:8px 0 0;}
"""


def _fm(v, cfg):
    return fmt_moneda(v, cfg)


def _kpis(rows: list[tuple[str, str]]) -> str:
    trs = "".join(f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>' for k, v in rows)
    return f'<table class="kpis">{trs}</table>'


def _card(titulo: str, body: str) -> str:
    return f'<div class="card"><h2>{titulo}</h2><div class="body">{body}</div></div>'


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
    a   = pnl["actual"]
    c   = pnl["comparativas"]
    res = a["resultado"]
    met = a["metricas"]
    ing = a["ingresos"]
    rows = [
        ("Ingresos netos (YTD)", _fm(ing.get("neto", ing["total"]), cfg)),
        ("Comisiones OTA",       _fm(ing.get("comisiones_ota", 0), cfg)),
        ("Gastos operativos",    _fm(a["gastos"]["total"], cfg)),
        (f"GOP — {'✅' if res['estado']=='positivo' else '🔴'} {res['estado']}",
         f"{_fm(res['gop'], cfg)} ({res['margen_pct'] or 0:.1f}%)"),
        ("GOP vs año anterior",  var_txt(c["gop"]["vs_año_anterior"])),
        ("Ocupación",            f"{met['ocupacion_pct'] or 0:.1f}%"),
        ("RevPAR",               _fm(met['revpar'] or 0, cfg)),
    ]
    return _card(f"📑 P&L — {pnl['mes_nombre']}", _kpis(rows) + _insights_block(insights))


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
        ("Ocupación (semana)",   f"{h7['ocupacion_pct']:.1f}%"),
        ("ADR (semana)",         _fm(h7["adr"], cfg)),
        ("RevPAR (semana)",      _fm(h7["revpar"], cfg)),
        ("Ocupación hoy",        f"{s['ocupacion_pct']:.1f}%"),
        ("ADR 30 días",          _fm(h30["adr"], cfg)),
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
            cfo_rows.append(("Inflación (IPC 12m)", f"{ana['ipc_acum_pct']:+.1f}%"))
        if ana["brecha_pp"] is not None:
            bp = ana["brecha_pp"]
            cls = "neg" if bp > 0 else "pos"
            signo = "por encima" if bp > 0 else "por debajo"
            cfo_rows.append(("Gasto vs inflación",
                             f'<span class="{cls}">{abs(bp):.1f} pp {signo}</span>'))
        body += ('<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">'
                 'Vista CFO — costos vs inflación</div>' + _kpis(cfo_rows))

        # Top categorías (12m)
        if ana["top_categorias"]:
            filas = "".join(
                f'<tr><td>{c["categoria"]}</td><td>{_fm(c["monto"], cfg)}</td><td>{c["pct"]:.0f}%</td></tr>'
                for c in ana["top_categorias"]
            )
            body += ('<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">'
                     'Top categorías (12m)</div>'
                     f'<table class="dt"><tr><th>Categoría</th><th>Monto</th><th>%</th></tr>{filas}</table>')

        # Top proveedores (12m)
        if ana["top_proveedores"]:
            filas = "".join(
                f'<tr><td>{p["proveedor"]}</td><td>{_fm(p["monto"], cfg)}</td><td>{p["n"]}</td></tr>'
                for p in ana["top_proveedores"]
            )
            body += ('<div style="margin-top:10px;font-size:12px;font-weight:700;color:#374151;">'
                     'Top proveedores (12m)</div>'
                     f'<table class="dt"><tr><th>Proveedor</th><th>Monto</th><th>Gastos</th></tr>{filas}</table>')

    return _card("📋 Control de Gastos", body)


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


_MESES_ABBR = {1:"ene",2:"feb",3:"mar",4:"abr",5:"may",6:"jun",
               7:"jul",8:"ago",9:"sep",10:"oct",11:"nov",12:"dic"}


def _sec_economia(ipc: dict | None) -> str:
    """
    Gráfico de barras (CSS puro) de la variación mensual del IPC de Chile,
    con eje cero real: los meses con inflación crecen hacia arriba y los de
    deflación hacia abajo del eje.
    """
    if not ipc or not ipc.get("serie"):
        return ""
    serie    = ipc["serie"]
    valores  = [p["valor"] for p in serie]
    escala   = max((abs(v) for v in valores), default=0) or 1
    alto_max = 46  # px por cada mitad (arriba del eje / abajo del eje)

    pos_cells = neg_cells = eje_cells = mes_cells = ""
    for p in serie:
        v   = p["valor"]
        mes = _MESES_ABBR.get(int(p["mes"][5:7]), p["mes"][5:7])
        if v > 0:   # inflación → barra hacia arriba (celda superior, pegada al eje)
            h = max(2, round(v / escala * alto_max))
            pos_cells += (
                '<td style="vertical-align:bottom;text-align:center;padding:0 2px;">'
                f'<div style="font-size:9px;color:#6b7280;">{v:+.1f}</div>'
                f'<div style="height:{h}px;background:#{COLOR.ALERTA:06x};border-radius:2px 2px 0 0;"></div></td>'
            )
            neg_cells += '<td></td>'
        elif v < 0:  # deflación → barra hacia abajo (celda inferior, pegada al eje)
            h = max(2, round(abs(v) / escala * alto_max))
            pos_cells += '<td></td>'
            neg_cells += (
                '<td style="vertical-align:top;text-align:center;padding:0 2px;">'
                f'<div style="height:{h}px;background:#3b82f6;border-radius:0 0 2px 2px;"></div>'
                f'<div style="font-size:9px;color:#6b7280;">{v:+.1f}</div></td>'
            )
        else:        # 0.0 → marca sobre el eje
            pos_cells += ('<td style="vertical-align:bottom;text-align:center;">'
                          '<div style="font-size:9px;color:#9ca3af;">0.0</div></td>')
            neg_cells += '<td></td>'
        eje_cells += '<td style="border-top:2px solid #cbd5e1;font-size:0;line-height:0;">&nbsp;</td>'
        mes_cells += f'<td style="text-align:center;font-size:9px;color:#9ca3af;padding-top:3px;">{mes}</td>'

    acum = ipc.get("acumulado_pct")
    sub  = (f"Inflación acumulada 12 meses: <b>{acum:+.1f}%</b> · "
            if acum is not None else "")
    body = (
        f'<div style="font-size:12px;color:#6b7280;margin-bottom:8px;">'
        f'{sub}variación mensual (%) · fuente: {ipc["fuente"]}</div>'
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;">'
        f'<tr style="height:{alto_max + 12}px">{pos_cells}</tr>'
        f'<tr>{eje_cells}</tr>'
        f'<tr style="height:{alto_max + 12}px">{neg_cells}</tr>'
        f'<tr>{mes_cells}</tr>'
        '</table>'
    )
    return _card("📉 Contexto económico — IPC Chile", body)


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
        + _sec_cierre(data["cierre"], cfg)
        + _sec_economia(data.get("ipc"))
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
