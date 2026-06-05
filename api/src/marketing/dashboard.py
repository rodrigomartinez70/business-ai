"""
Sección de Marketing (HORIZONTAL) para el dashboard semanal.

Lee `insights_marketing` + `campanas` del schema del tenant (search_path) y calcula
las métricas de performance publicitaria (Meta Ads). Comparativa vs período anterior.

`calcular_marketing()` devuelve None si el tenant no tiene tablas/datos de marketing,
para que el dashboard simplemente omita la sección (no la muestra vacía).
"""

import logging
from datetime import date, timedelta

import asyncpg

from src import config
from src.render import _CSS, _card, _kpis, _fm, _aviso

logger = logging.getLogger(__name__)


def _div(a: float, b: float) -> float:
    return (a / b) if b else 0.0


async def calcular_marketing(hasta: date, dias: int = 61, *, conn=None) -> dict | None:
    """Métricas de marketing del período. Si se pasa `conn` (asyncpg) usa esa
    conexión; si no, toma una del pool tenant-aware (contexto de request)."""
    if conn is not None:
        return await _calcular_marketing(conn, hasta, dias)
    async with config.db_pool.acquire() as c:
        return await _calcular_marketing(c, hasta, dias)


async def _calcular_marketing(conn, hasta: date, dias: int) -> dict | None:
    desde     = hasta - timedelta(days=dias - 1)
    ant_hasta = desde - timedelta(days=1)
    ant_desde = ant_hasta - timedelta(days=dias - 1)

    try:
        tot = await conn.fetchrow("""
            SELECT COALESCE(SUM(gasto),0)        AS gasto,
                   COALESCE(SUM(conversiones),0) AS leads,
                   COALESCE(SUM(clics),0)        AS clics,
                   COALESCE(SUM(impresiones),0)  AS impresiones,
                   COALESCE(SUM(alcance),0)      AS alcance,
                   COUNT(*)                      AS filas
              FROM insights_marketing WHERE fecha BETWEEN $1 AND $2
        """, desde, hasta)
        if not tot or tot["filas"] == 0:
            return None

        ant = await conn.fetchrow("""
            SELECT COALESCE(SUM(gasto),0) AS gasto, COALESCE(SUM(conversiones),0) AS leads,
                   COALESCE(SUM(impresiones),0) AS impresiones, COALESCE(SUM(clics),0) AS clics
              FROM insights_marketing WHERE fecha BETWEEN $1 AND $2
        """, ant_desde, ant_hasta)

        serie = await conn.fetch("""
            SELECT fecha,
                   COALESCE(SUM(gasto),0)        AS gasto,
                   COALESCE(SUM(impresiones),0)  AS impresiones,
                   COALESCE(SUM(clics),0)        AS clics,
                   COALESCE(SUM(alcance),0)      AS alcance,
                   COALESCE(SUM(conversiones),0) AS conversiones
              FROM insights_marketing WHERE fecha BETWEEN $1 AND $2
             GROUP BY fecha ORDER BY fecha
        """, desde, hasta)

        camp = await conn.fetch("""
            SELECT c.nombre, c.estado, c.objetivo, c.presupuesto_diario,
                   COALESCE(SUM(i.gasto),0)        AS gasto,
                   COALESCE(SUM(i.conversiones),0) AS leads,
                   COALESCE(SUM(i.clics),0)        AS clics,
                   COALESCE(SUM(i.impresiones),0)  AS impresiones
              FROM campanas c
              LEFT JOIN insights_marketing i
                     ON i.campana_id = c.id AND i.fecha BETWEEN $1 AND $2
             GROUP BY c.id, c.nombre, c.estado, c.objetivo, c.presupuesto_diario
             ORDER BY SUM(i.gasto) DESC NULLS LAST
        """, desde, hasta)
    except (asyncpg.UndefinedTableError, asyncpg.InvalidSchemaNameError):
        return None  # tenant sin esquema de marketing
    except Exception as e:  # defensivo: nunca romper el dashboard por marketing
        logger.warning(f"marketing no disponible: {e}")
        return None

    gasto = float(tot["gasto"]); leads = float(tot["leads"])
    clics = int(tot["clics"]); impresiones = int(tot["impresiones"]); alcance = int(tot["alcance"])
    g_ant = float(ant["gasto"]); l_ant = float(ant["leads"])
    i_ant = int(ant["impresiones"]); c_ant = int(ant["clics"])

    resumen = {
        "inversion": gasto, "leads": leads, "clics": clics, "impresiones": impresiones,
        "alcance": alcance,
        "cpl": _div(gasto, leads), "cpc": _div(gasto, clics),
        "ctr": _div(clics, impresiones) * 100, "cpm": _div(gasto, impresiones) * 1000,
        "conversion_clic_lead": _div(leads, clics) * 100,
        "var_inversion_pct":   (_div(gasto - g_ant, g_ant) * 100) if g_ant else None,
        "var_leads_pct":       (_div(leads - l_ant, l_ant) * 100) if l_ant else None,
        "var_impresiones_pct": (_div(impresiones - i_ant, i_ant) * 100) if i_ant else None,
        "var_clics_pct":       (_div(clics - c_ant, c_ant) * 100) if c_ant else None,
    }

    campanas: list[dict] = []
    alertas: list[dict] = []
    for c in camp:
        g = float(c["gasto"]); l = float(c["leads"])
        campanas.append({"nombre": c["nombre"], "estado": c["estado"], "objetivo": c["objetivo"],
                         "gasto": g, "leads": l, "cpl": _div(g, l),
                         "clics": int(c["clics"]), "impresiones": int(c["impresiones"])})
        if c["estado"] == "PAUSED" and (c["presupuesto_diario"] or 0) > 0:
            alertas.append({"nivel": "info", "titulo": f"Campaña pausada con presupuesto: {c['nombre']}",
                            "desc": "Tiene presupuesto asignado pero está en pausa."})
        if g > 0 and l == 0:
            alertas.append({"nivel": "alerta", "titulo": f"Gasto sin leads: {c['nombre']}",
                            "desc": "La campaña gastó sin generar conversiones en el período."})

    activas = [c for c in campanas if c["leads"] > 0]
    mejor = min(activas, key=lambda c: c["cpl"]) if activas else None
    peor  = max(activas, key=lambda c: c["cpl"]) if activas else None

    serie_diaria = [{"fecha": str(s["fecha"]), "gasto": float(s["gasto"]),
                     "impresiones": int(s["impresiones"]), "clics": int(s["clics"]),
                     "alcance": int(s["alcance"]), "conversiones": float(s["conversiones"])}
                    for s in serie]

    return {
        "periodo": {"desde": str(desde), "hasta": str(hasta), "dias": dias},
        "resumen": resumen,
        "campanas": campanas,
        "alertas": alertas,
        "serie_diaria": serie_diaria,
        "mejor_campana": mejor["nombre"] if mejor else None,
        "peor_campana":  peor["nombre"] if peor else None,
    }


def _insights_block(insights) -> str:
    if not insights:
        return ""
    lis = "".join(f"<li>{i}</li>" for i in insights)
    return (f'<div class="ins"><div class="t">💡 Insights IA</div>'
            f'<ul style="margin:0;padding-left:16px;">{lis}</ul></div>')


def renderizar_marketing_html(data: dict, cfg: dict, insights=None) -> str:
    r = data["resumen"]; p = data["periodo"]

    def vtxt(v):
        return f"{v:+.1f}%" if v is not None else "—"

    rows = [
        ("Inversión publicitaria", f"{_fm(r['inversion'], cfg)} ({vtxt(r['var_inversion_pct'])})"),
        ("Leads generados",        f"{r['leads']:,.0f} ({vtxt(r['var_leads_pct'])})"),
        ("CPL — costo por lead",   _fm(r["cpl"], cfg)),
        ("Conversión clic→lead",   f"{r['conversion_clic_lead']:.1f}%"),
        ("CPC / CTR",              f"{_fm(r['cpc'], cfg)} / {r['ctr']:.2f}%"),
        ("Alcance",                f"{r['alcance']:,.0f}"),
    ]

    filas = ""
    for c in data["campanas"]:
        if c["nombre"] == data.get("mejor_campana"):
            ico = "✅ "
        elif c["estado"] == "PAUSED":
            ico = "⏸ "
        else:
            ico = ""
        cpl = _fm(c["cpl"], cfg) if c["leads"] else "—"
        filas += (f'<tr><td>{ico}{c["nombre"]}</td><td>{_fm(c["gasto"], cfg)}</td>'
                  f'<td style="text-align:right;">{c["leads"]:,.0f}</td><td>{cpl}</td></tr>')
    tabla = (f'<table class="dt"><tr><th>Campaña</th><th>Gasto</th><th>Leads</th>'
             f'<th>CPL</th></tr>{filas}</table>')

    avisos = "".join(_aviso(a["nivel"], a["titulo"], a["desc"]) for a in data["alertas"])

    return _card(f"📣 Marketing — Meta Ads (últimos {p['dias']} días)",
                 _kpis(rows) + tabla + avisos + _insights_block(insights))


def renderizar_marketing_pagina(data: dict, cfg: dict, titulo: str = "Marketing",
                                insights=None) -> str:
    """Página HTML standalone (documento completo) con la sección de marketing.
    Útil para generar un dashboard de marketing independiente por tenant."""
    p = data.get("periodo", {})
    card = renderizar_marketing_html(data, cfg, insights)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard de Marketing — {titulo}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<div class="head"><h1>📣 Dashboard de Marketing — {titulo}</h1>
<div class="sub">Período {p.get('desde', '')} → {p.get('hasta', '')} · fuente: Meta Ads</div></div>
{card}
<div class="foot">Datos de Meta Ads almacenados en PostgreSQL · generado automáticamente.</div>
</div></body></html>"""


# ─────────────────────────────────────────────────────────────
# Render GRÁFICO (estilo "Resumen de publicidad" de Meta)
# ─────────────────────────────────────────────────────────────

_SPARK = "#0a7d6b"

_OBJ_LABEL = {
    "OUTCOME_LEADS": "Leads", "LEAD_GENERATION": "Leads",
    "OUTCOME_TRAFFIC": "Tráfico", "LINK_CLICKS": "Tráfico",
    "OUTCOME_AWARENESS": "Reconocimiento", "BRAND_AWARENESS": "Reconocimiento",
    "REACH": "Reconocimiento", "OUTCOME_ENGAGEMENT": "Interacción",
    "POST_ENGAGEMENT": "Interacción", "OUTCOME_SALES": "Ventas", "CONVERSIONS": "Ventas",
}


def _num(n) -> str:
    """Entero con separador de miles estilo chileno (punto)."""
    return f"{n:,.0f}".replace(",", ".")


def _sparkline(valores, w: int = 260, h: int = 44, color: str = _SPARK) -> str:
    vals = [float(v) for v in valores] if valores else []
    if len(vals) < 2:
        vals = (vals * 2) if vals else [0.0, 0.0]
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1.0
    n = len(vals); pad = 3
    pts = []
    for i, v in enumerate(vals):
        x = pad + i / (n - 1) * (w - 2 * pad)
        y = pad + (1 - (v - mn) / rng) * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    return (f'<svg width="100%" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'style="display:block;margin-top:8px;">'
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>')


def _kpi_card(titulo: str, valor: str, var_pct, serie) -> str:
    if var_pct is None:
        trend = '<span style="color:#9ca3af;font-size:13px;font-weight:600;">—</span>'
    else:
        up = var_pct >= 0
        col = "#16a34a" if up else "#dc2626"
        trend = (f'<span style="color:{col};font-size:13px;font-weight:700;">'
                 f'{"▲" if up else "▼"} {abs(var_pct):.1f}%</span>')
    return (
        '<div style="flex:1 1 200px;border:1px solid #e5e7eb;border-radius:12px;'
        'padding:14px 16px;background:#fff;">'
        f'<div style="font-size:13px;color:#374151;font-weight:600;margin-bottom:8px;">{titulo}</div>'
        f'<div style="font-size:30px;font-weight:800;line-height:1;color:#111827;">'
        f'{valor} &nbsp;{trend}</div>'
        f'{_sparkline(serie)}</div>'
    )


def _tabla_objetivo(grupo: str, camps: list[dict], cfg: dict) -> str:
    total_g = sum(c["gasto"] for c in camps)
    if grupo == "Leads":
        cols = "<th>Campaña</th><th>Inversión</th><th>Conversiones</th><th>Costo x conv.</th>"
        filas = ""
        for c in camps:
            cpl = _fm(c["cpl"], cfg) if c["leads"] else "—"
            filas += (f'<tr><td>{c["nombre"]}</td><td>{_fm(c["gasto"], cfg)}</td>'
                      f'<td style="text-align:right;">{_num(c["leads"])}</td><td>{cpl}</td></tr>')
    else:
        cols = "<th>Campaña</th><th>Inversión</th><th>Impresiones</th><th>Clics</th><th>Costo x clic</th>"
        filas = ""
        for c in camps:
            cpc = _fm(_div(c["gasto"], c["clics"]), cfg) if c["clics"] else "—"
            filas += (f'<tr><td>{c["nombre"]}</td><td>{_fm(c["gasto"], cfg)}</td>'
                      f'<td style="text-align:right;">{_num(c["impresiones"])}</td>'
                      f'<td style="text-align:right;">{_num(c["clics"])}</td><td>{cpc}</td></tr>')
    return _card(
        f"Campañas de {grupo} · inversión {_fm(total_g, cfg)}",
        f'<table class="dt"><tr>{cols}</tr>{filas}</table>')


def renderizar_marketing_grafico(data: dict, cfg: dict, titulo: str = "Marketing") -> str:
    r = data["resumen"]; p = data["periodo"]
    serie = data.get("serie_diaria", [])
    n_camp = len([c for c in data["campanas"] if c["gasto"] > 0])

    cards = (
        _kpi_card("Inversión", _fm(r["inversion"], cfg), r.get("var_inversion_pct"),
                  [d["gasto"] for d in serie])
        + _kpi_card("Espectadores (impresiones)", _num(r["impresiones"]),
                    r.get("var_impresiones_pct"), [d["impresiones"] for d in serie])
        + _kpi_card("Clics en el enlace", _num(r["clics"]),
                    r.get("var_clics_pct"), [d["clics"] for d in serie])
        + _kpi_card("Conversiones", _num(r["leads"]),
                    r.get("var_leads_pct"), [d["conversiones"] for d in serie])
    )
    cards_row = f'<div style="display:flex;gap:12px;flex-wrap:wrap;margin:4px 0 18px;">{cards}</div>'

    # Tablas agrupadas por objetivo (orden: Leads, Tráfico, resto por inversión)
    grupos: dict[str, list[dict]] = {}
    for c in data["campanas"]:
        if c["gasto"] <= 0:
            continue
        grupos.setdefault(_OBJ_LABEL.get(c.get("objetivo"), "Otras"), []).append(c)
    orden = sorted(grupos, key=lambda g: (g != "Leads", g != "Tráfico",
                                          -sum(x["gasto"] for x in grupos[g])))
    tablas = "".join(_tabla_objetivo(g, grupos[g], cfg) for g in orden)

    avisos = "".join(_aviso(a["nivel"], a["titulo"], a["desc"]) for a in data.get("alertas", []))
    avisos_card = _card("⚠️ Puntos de atención", avisos) if avisos else ""

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Resumen de publicidad — {titulo}</title>
<style>{_CSS}</style></head>
<body><div class="wrap">
<div class="head" style="text-align:left;">
  <h1 style="font-size:20px;">Resumen de publicidad — {titulo}</h1>
  <div class="sub">{titulo} gastó <b>{_fm(r['inversion'], cfg)}</b> en {n_camp} campañas
  en los últimos {p['dias']} días · {p['desde']} → {p['hasta']} · fuente: Meta Ads</div>
</div>
{cards_row}
{tablas}
{avisos_card}
<div class="foot">Datos de Meta Ads almacenados en PostgreSQL · generado automáticamente.</div>
</div></body></html>"""
