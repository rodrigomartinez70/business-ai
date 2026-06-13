"""
Dashboard web (HTML interactivo) por empresa — distinto del correo.

El correo (informe.py) es estático e inline para clientes de mail. Esto es una
PÁGINA web pensada para abrir a diario en el navegador: KPIs grandes, gráficas
(Chart.js) y tablas clave. No calcula nada: consume el mismo `calcular_informe()`.

`renderizar_dashboard_web(data, cfg, biz)` → str (HTML completo, self-contained).
"""

import json
from datetime import date


def _m(v) -> str:
    """Monto CLP. None → '—'; negativos en rojo."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    s = f"-${abs(f):,.0f}" if f < 0 else f"${f:,.0f}"
    return f'<span style="color:#dc2626">{s}</span>' if f < 0 else s


def _pct(v) -> str:
    if v is None:
        return ""
    cls = "neg" if v < 0 else "pos"
    return f'<span class="delta {cls}">{v:+.1f}%</span>'


_SEM_COLOR = {"ok": "#16a34a", "alerta": "#d97706", "critico": "#dc2626", "info": "#2563eb"}


def _tile(label: str, valor: str, sub: str = "", accent: str = "#2563eb") -> str:
    sub_html = f'<div class="tile-sub">{sub}</div>' if sub else ""
    return (f'<div class="tile" style="--accent:{accent}">'
            f'<div class="tile-label">{label}</div>'
            f'<div class="tile-val">{valor}</div>{sub_html}</div>')


def _extraer(data: dict) -> dict:
    """Aplana lo que necesita la vista desde {corte, dash, panel}."""
    dash = data.get("dash", {}) or {}
    panel = data.get("panel", {}) or {}
    cfo = (panel.get("cfo") or {})
    ind = cfo.get("indicadores", {}) or {}
    tes = panel.get("tesoreria", {}) or {}
    cxc = panel.get("cuentas_por_cobrar", {}) or {}
    cxp = panel.get("cuentas_por_pagar", {}) or {}
    cierre = dash.get("cierre") or {}
    gastos = dash.get("gastos") or {}
    f29 = ((dash.get("tributario") or {}).get("agente_iva") or {}).get("f29", {}) or {}
    return {
        "cfo": cfo, "ind": ind, "tes": tes, "cxc": cxc, "cxp": cxp,
        "cierre": cierre, "gastos": gastos, "f29": f29,
    }


def renderizar_dashboard_web(data: dict, cfg: dict, biz: str) -> str:
    e = _extraer(data)
    corte = data.get("corte", str(date.today()))
    cfo, ind, tes, cxc, cxp = e["cfo"], e["ind"], e["tes"], e["cxc"], e["cxp"]
    cierre, gastos, f29 = e["cierre"], e["gastos"], e["f29"]

    # ── KPI tiles ──
    rent = ind.get("rentabilidad") or {}
    ventas_mes = (cierre.get("totales") or {}).get("total")
    tiles = []
    if ventas_mes is not None:
        tiles.append(_tile("Ventas del mes", _m(ventas_mes),
                           f'{(cierre.get("totales") or {}).get("n", 0)} documentos', "#2563eb"))
    if tes.get("caja_estimada") is not None:
        tiles.append(_tile("Caja estimada", _m(tes["caja_estimada"]),
                           f'proyección 8 sem: {_m(tes.get("caja_proyectada_8sem"))}', "#0891b2"))
    if cxc.get("total_por_cobrar") is not None:
        dso = cxc.get("dso")
        tiles.append(_tile("Por cobrar", _m(cxc["total_por_cobrar"]),
                           f'DSO {dso:.0f} días' if dso is not None else "", "#16a34a"))
    if cxp.get("total_por_pagar") is not None:
        tiles.append(_tile("Por pagar", _m(cxp["total_por_pagar"]),
                           f'vencido {_m(cxp.get("vencido"))}', "#d97706"))
    if f29.get("total_a_pagar") is not None:
        tiles.append(_tile("F29 a pagar", _m(f29["total_a_pagar"]),
                           f'vence {f29.get("vencimiento", "N/A")}', "#7c3aed"))
    if rent.get("resultado_neto") is not None:
        tiles.append(_tile("Resultado neto", _m(rent["resultado_neto"]),
                           f'margen bruto {rent.get("margen_bruto_pct", 0):.0f}%', "#db2777"))
    tiles_html = "".join(tiles) or '<div class="empty">Sin datos suficientes todavía.</div>'

    # ── Semáforo + puntos clave (CFO) ──
    sem = cfo.get("semaforo", "info")
    puntos = cfo.get("puntos_clave", []) or []
    if puntos:
        lis = "".join(f'<li><span class="dot" style="background:{_SEM_COLOR.get(p.get("nivel"), "#6b7280")}"></span>'
                      f'{p.get("texto", "")}</li>' for p in puntos)
        puntos_html = f'<ul class="puntos">{lis}</ul>'
    else:
        puntos_html = '<p class="ok-msg">Sin alertas: indicadores dentro de lo esperado.</p>'

    # ── Tabla: propuesta de pagos (Tesorería) ──
    prop = tes.get("propuesta_pagos", []) or []
    if prop:
        filas = "".join(f'<tr><td>{p.get("vence", "")}</td><td>{p.get("proveedor", "")}</td>'
                        f'<td class="r">{_m(p.get("monto"))}</td>'
                        f'<td><span class="pill {"pay" if p.get("accion") == "pagar" else "wait"}">'
                        f'{"Pagar" if p.get("accion") == "pagar" else "Postergar"}</span></td></tr>'
                        for p in prop[:8])
        pagos_html = (f'<table class="dt"><thead><tr><th>Vence</th><th>Proveedor</th>'
                      f'<th class="r">Monto</th><th>Acción</th></tr></thead><tbody>{filas}</tbody></table>')
    else:
        pagos_html = '<p class="muted">Sin pagos próximos en la propuesta.</p>'

    # ── Datos para gráficas (Chart.js) ──
    dias = cierre.get("dias", []) or []
    chart_ventas = {
        "labels": [d["fecha"][5:] for d in dias],
        "facturas": [d["facturas"] for d in dias],
        "boletas": [d["boletas"] for d in dias],
    }
    cats = (gastos.get("categorias") or [])[:7]
    chart_gastos = {
        "labels": [c["categoria"] for c in cats],
        "data": [c["monto_actual"] for c in cats],
    }
    chart_posicion = {
        "cobrar": cxc.get("total_por_cobrar") or 0,
        "pagar": cxp.get("total_por_pagar") or 0,
    }
    payload = json.dumps({"ventas": chart_ventas, "gastos": chart_gastos,
                          "posicion": chart_posicion}, ensure_ascii=False)

    sem_color = _SEM_COLOR.get(sem, "#6b7280")
    return _PAGINA.format(biz=biz, corte=corte, sem=sem.upper(), sem_color=sem_color,
                          tiles=tiles_html, puntos=puntos_html, pagos=pagos_html,
                          payload=payload)


_PAGINA = """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{biz} — Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  *{{box-sizing:border-box}}
  body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
       background:#f1f5f9;color:#0f172a}}
  .hero{{background:linear-gradient(120deg,#1e3a8a,#2563eb);color:#fff;padding:28px 32px}}
  .hero h1{{margin:0;font-size:24px;font-weight:700}}
  .hero .sub{{opacity:.85;font-size:14px;margin-top:4px}}
  .badge{{display:inline-block;margin-top:10px;padding:3px 12px;border-radius:999px;
         font-size:12px;font-weight:700;background:{sem_color};color:#fff;text-transform:uppercase}}
  .wrap{{max-width:1100px;margin:0 auto;padding:24px 20px 48px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:-44px 0 22px}}
  .tile{{background:#fff;border-radius:14px;padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08);
        border-top:3px solid var(--accent)}}
  .tile-label{{font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.4px}}
  .tile-val{{font-size:24px;font-weight:700;margin-top:4px}}
  .tile-sub{{font-size:12px;color:#94a3b8;margin-top:3px}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}
  .card{{background:#fff;border-radius:14px;padding:18px 20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
  .card h2{{margin:0 0 14px;font-size:15px;color:#0f172a}}
  .card.wide{{grid-column:1/-1}}
  canvas{{max-height:280px}}
  .puntos{{list-style:none;margin:0;padding:0}}
  .puntos li{{display:flex;align-items:center;gap:8px;font-size:14px;padding:5px 0;color:#334155}}
  .dot{{width:9px;height:9px;border-radius:50%;flex:0 0 auto}}
  .ok-msg{{color:#16a34a;font-size:14px;margin:0}}
  .dt{{width:100%;border-collapse:collapse;font-size:13px}}
  .dt th{{text-align:left;padding:7px 10px;background:#f8fafc;color:#64748b;font-size:12px;
         border-bottom:1px solid #e2e8f0}}
  .dt td{{padding:7px 10px;border-bottom:1px solid #f1f5f9;color:#334155}}
  .dt .r,th.r{{text-align:right}}
  .pill{{padding:2px 9px;border-radius:999px;font-size:11px;font-weight:600}}
  .pill.pay{{background:#dcfce7;color:#166534}}
  .pill.wait{{background:#fef3c7;color:#92400e}}
  .delta{{font-size:12px;font-weight:600}} .delta.pos{{color:#16a34a}} .delta.neg{{color:#dc2626}}
  .muted,.empty{{color:#94a3b8;font-size:13px}}
  .foot{{text-align:center;color:#94a3b8;font-size:11px;margin-top:26px}}
</style></head>
<body>
  <div class="hero">
    <h1>{biz}</h1>
    <div class="sub">Dashboard financiero · corte {corte}</div>
    <span class="badge">{sem}</span>
  </div>
  <div class="wrap">
    <div class="grid">{tiles}</div>
    <div class="cards">
      <div class="card wide"><h2>Ventas diarias (facturas vs boletas)</h2>
        <canvas id="cVentas"></canvas></div>
      <div class="card"><h2>Gastos por categoría</h2><canvas id="cGastos"></canvas></div>
      <div class="card"><h2>Posición: por cobrar vs por pagar</h2><canvas id="cPos"></canvas></div>
      <div class="card"><h2>Resumen ejecutivo</h2>{puntos}</div>
      <div class="card"><h2>Propuesta de pagos</h2>{pagos}</div>
    </div>
    <div class="foot">Generado por majorbi · datos del SII + banco + integraciones de la empresa</div>
  </div>
<script>
const D = {payload};
const CLP = v => '$' + Math.round(v).toLocaleString('es-CL');
const opts = {{responsive:true, plugins:{{legend:{{position:'bottom'}}}},
  scales:{{y:{{ticks:{{callback:CLP}}}}}}}};
if (D.ventas.labels.length) new Chart(cVentas, {{type:'bar', data:{{labels:D.ventas.labels,
  datasets:[{{label:'Facturas',data:D.ventas.facturas,backgroundColor:'#2563eb'}},
            {{label:'Boletas',data:D.ventas.boletas,backgroundColor:'#60a5fa'}}]}},
  options:{{...opts, scales:{{x:{{stacked:true}}, y:{{stacked:true,ticks:{{callback:CLP}}}}}}}}}});
if (D.gastos.labels.length) new Chart(cGastos, {{type:'doughnut', data:{{labels:D.gastos.labels,
  datasets:[{{data:D.gastos.data, backgroundColor:['#2563eb','#0891b2','#16a34a','#d97706','#db2777','#7c3aed','#64748b']}}]}},
  options:{{responsive:true, plugins:{{legend:{{position:'right'}}}}}}}});
new Chart(cPos, {{type:'bar', data:{{labels:['Por cobrar','Por pagar'],
  datasets:[{{data:[D.posicion.cobrar,D.posicion.pagar], backgroundColor:['#16a34a','#d97706']}}]}},
  options:{{...opts, plugins:{{legend:{{display:false}}}}}}}});
</script>
</body></html>"""
