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
from src.render import _CSS, _card, _kpis, _fm

# Nombre visible de la plataforma (una PyME usa una sola fuente de marketing).
_FUENTE_LABEL = {"meta": "Meta Ads", "google": "Google Ads"}

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
            SELECT COALESCE(SUM(gasto),0)         AS gasto,
                   COALESCE(SUM(conversiones),0)  AS leads,
                   COALESCE(SUM(clics),0)         AS clics,
                   COALESCE(SUM(impresiones),0)   AS impresiones,
                   COALESCE(SUM(alcance),0)       AS alcance,
                   COALESCE(SUM(mensajes),0)      AS mensajes,
                   COALESCE(SUM(interacciones),0) AS interacciones,
                   COALESCE(SUM(reproducciones),0) AS reproducciones,
                   COALESCE(SUM(visitas_perfil),0) AS visitas_perfil,
                   COUNT(*)                       AS filas
              FROM insights_marketing WHERE fecha BETWEEN $1 AND $2
        """, desde, hasta)
        if not tot or tot["filas"] == 0:
            return None

        ant = await conn.fetchrow("""
            SELECT COALESCE(SUM(gasto),0) AS gasto, COALESCE(SUM(conversiones),0) AS leads,
                   COALESCE(SUM(impresiones),0) AS impresiones, COALESCE(SUM(clics),0) AS clics,
                   COALESCE(SUM(interacciones),0) AS interacciones,
                   COALESCE(SUM(mensajes),0) AS mensajes
              FROM insights_marketing WHERE fecha BETWEEN $1 AND $2
        """, ant_desde, ant_hasta)

        serie = await conn.fetch("""
            SELECT fecha,
                   COALESCE(SUM(gasto),0)         AS gasto,
                   COALESCE(SUM(impresiones),0)   AS impresiones,
                   COALESCE(SUM(clics),0)         AS clics,
                   COALESCE(SUM(alcance),0)       AS alcance,
                   COALESCE(SUM(conversiones),0)  AS conversiones,
                   COALESCE(SUM(mensajes),0)      AS mensajes,
                   COALESCE(SUM(interacciones),0) AS interacciones,
                   COALESCE(SUM(reproducciones),0) AS reproducciones,
                   COALESCE(SUM(visitas_perfil),0) AS visitas_perfil
              FROM insights_marketing WHERE fecha BETWEEN $1 AND $2
             GROUP BY fecha ORDER BY fecha
        """, desde, hasta)

        camp = await conn.fetch("""
            SELECT c.nombre, c.estado, c.objetivo, c.presupuesto_diario,
                   COALESCE(SUM(i.gasto),0)         AS gasto,
                   COALESCE(SUM(i.conversiones),0)  AS leads,
                   COALESCE(SUM(i.clics),0)         AS clics,
                   COALESCE(SUM(i.impresiones),0)   AS impresiones,
                   COALESCE(SUM(i.mensajes),0)      AS mensajes,
                   COALESCE(SUM(i.interacciones),0) AS interacciones,
                   COALESCE(SUM(i.reproducciones),0) AS reproducciones,
                   COALESCE(SUM(i.visitas_perfil),0) AS visitas_perfil
              FROM campanas c
              LEFT JOIN insights_marketing i
                     ON i.campana_id = c.id AND i.fecha BETWEEN $1 AND $2
             GROUP BY c.id, c.nombre, c.estado, c.objetivo, c.presupuesto_diario
             ORDER BY SUM(i.gasto) DESC NULLS LAST
        """, desde, hasta)

        plats = await conn.fetch(
            "SELECT DISTINCT cm.plataforma FROM canales_marketing cm "
            "JOIN campanas c ON c.canal_id = cm.id")
    except (asyncpg.UndefinedTableError, asyncpg.InvalidSchemaNameError):
        return None  # tenant sin esquema de marketing
    except Exception as e:  # defensivo: nunca romper el dashboard por marketing
        logger.warning(f"marketing no disponible: {e}")
        return None

    gasto = float(tot["gasto"]); leads = float(tot["leads"])
    clics = int(tot["clics"]); impresiones = int(tot["impresiones"]); alcance = int(tot["alcance"])
    mensajes = int(tot["mensajes"]); interacciones = int(tot["interacciones"])
    reproducciones = int(tot["reproducciones"]); visitas_perfil = int(tot["visitas_perfil"])
    g_ant = float(ant["gasto"]); l_ant = float(ant["leads"])
    i_ant = int(ant["impresiones"]); c_ant = int(ant["clics"])
    int_ant = int(ant["interacciones"]); m_ant = int(ant["mensajes"])

    resumen = {
        "inversion": gasto, "leads": leads, "clics": clics, "impresiones": impresiones,
        "alcance": alcance, "mensajes": mensajes, "interacciones": interacciones,
        "reproducciones": reproducciones, "visitas_perfil": visitas_perfil,
        "cpl": _div(gasto, leads), "cpc": _div(gasto, clics),
        "costo_mensaje": _div(gasto, mensajes), "costo_visita": _div(gasto, visitas_perfil),
        "ctr": _div(clics, impresiones) * 100, "cpm": _div(gasto, impresiones) * 1000,
        "conversion_clic_lead": _div(leads, clics) * 100,
        "var_inversion_pct":     (_div(gasto - g_ant, g_ant) * 100) if g_ant else None,
        "var_leads_pct":         (_div(leads - l_ant, l_ant) * 100) if l_ant else None,
        "var_impresiones_pct":   (_div(impresiones - i_ant, i_ant) * 100) if i_ant else None,
        "var_clics_pct":         (_div(clics - c_ant, c_ant) * 100) if c_ant else None,
        "var_interacciones_pct": (_div(interacciones - int_ant, int_ant) * 100) if int_ant else None,
        "var_mensajes_pct":      (_div(mensajes - m_ant, m_ant) * 100) if m_ant else None,
    }

    campanas: list[dict] = []
    for c in camp:
        g = float(c["gasto"]); l = float(c["leads"])
        campanas.append({"nombre": c["nombre"], "estado": c["estado"], "objetivo": c["objetivo"],
                         "presupuesto_diario": float(c["presupuesto_diario"] or 0),
                         "gasto": g, "leads": l, "cpl": _div(g, l),
                         "clics": int(c["clics"]), "impresiones": int(c["impresiones"]),
                         "mensajes": int(c["mensajes"]), "interacciones": int(c["interacciones"]),
                         "reproducciones": int(c["reproducciones"]),
                         "visitas_perfil": int(c["visitas_perfil"])})

    activas = [c for c in campanas if c["leads"] > 0]
    mejor = min(activas, key=lambda c: c["cpl"]) if activas else None
    peor  = max(activas, key=lambda c: c["cpl"]) if activas else None

    serie_diaria = [{"fecha": str(s["fecha"]), "gasto": float(s["gasto"]),
                     "impresiones": int(s["impresiones"]), "clics": int(s["clics"]),
                     "alcance": int(s["alcance"]), "conversiones": float(s["conversiones"]),
                     "mensajes": int(s["mensajes"]), "interacciones": int(s["interacciones"]),
                     "reproducciones": int(s["reproducciones"]),
                     "visitas_perfil": int(s["visitas_perfil"])}
                    for s in serie]

    # Plataforma activa (una PyME usa una sola fuente de marketing).
    plataformas = sorted({p["plataforma"] for p in plats if p["plataforma"]})
    plataforma = plataformas[0] if len(plataformas) == 1 else None

    return {
        "periodo": {"desde": str(desde), "hasta": str(hasta), "dias": dias},
        "resumen": resumen,
        "campanas": campanas,
        "plataforma": plataforma,
        "fuente_label": _FUENTE_LABEL.get(plataforma, "Marketing"),
        "serie_diaria": serie_diaria,
        "mejor_campana": mejor["nombre"] if mejor else None,
        "peor_campana":  peor["nombre"] if peor else None,
    }


def renderizar_marketing_html(data: dict, cfg: dict) -> str:
    r = data["resumen"]; p = data["periodo"]
    fuente = data.get("fuente_label", "Marketing")

    def vtxt(v):
        return f"{v:+.1f}%" if v is not None else "—"

    # KPI principal dinámica según el objetivo dominante de las campañas:
    #   lead-gen → Leads / CPL · mensajería (WhatsApp/DM) → Mensajes / Costo x mensaje
    #   sin conversiones → tráfico → Clics / CPC. Se elige el de mayor volumen.
    leads = r["leads"]; mensajes = r["mensajes"]
    if leads >= mensajes and leads > 0:
        modo = "leads"
    elif mensajes > 0:
        modo = "mensajes"
    else:
        modo = "trafico"

    rows = [("Inversión publicitaria",
             f"{_fm(r['inversion'], cfg)} ({vtxt(r['var_inversion_pct'])})")]
    if modo == "leads":
        rows += [
            ("Leads generados",      f"{leads:,.0f} ({vtxt(r['var_leads_pct'])})"),
            ("CPL — costo por lead", _fm(r["cpl"], cfg)),
            ("Conversión clic→lead", f"{r['conversion_clic_lead']:.1f}%"),
        ]
        res_col, cost_col = "Leads", "CPL"
    elif modo == "mensajes":
        rows += [
            ("Mensajes iniciados",      f"{mensajes:,.0f} ({vtxt(r['var_mensajes_pct'])})"),
            ("Costo por mensaje",       _fm(r["costo_mensaje"], cfg)),
            ("Conversión clic→mensaje", f"{_div(mensajes, r['clics']) * 100:.1f}%"),
        ]
        res_col, cost_col = "Mensajes", "Costo x msj"
    else:
        rows += [("Clics generados", f"{r['clics']:,.0f} ({vtxt(r['var_clics_pct'])})")]
        res_col, cost_col = "Clics", "CPC"
    rows.append(("CPC / CTR", f"{_fm(r['cpc'], cfg)} / {r['ctr']:.2f}%"))
    # Alcance: solo lo entrega Meta (Google Ads no expone "reach") → métrica dinámica.
    if data.get("plataforma") == "meta":
        rows.append(("Alcance", f"{r['alcance']:,.0f}"))

    # Resultado/costo por campaña según el modo (mismo eje que la KPI principal).
    def _resultado(c):
        return {"leads": c["leads"], "mensajes": c["mensajes"], "trafico": c["clics"]}[modo]

    def _costo(c):
        v = _resultado(c)
        return _fm(_div(c["gasto"], v), cfg) if v else "—"

    # Solo los proyectos/campañas que tienen presupuesto asignado.
    con_presupuesto = [c for c in data["campanas"] if (c.get("presupuesto_diario") or 0) > 0]
    filas = ""
    for c in con_presupuesto:
        if c["nombre"] == data.get("mejor_campana"):
            ico = "✅ "
        elif c["estado"] == "PAUSED":
            ico = "⏸ "
        else:
            ico = ""
        filas += (f'<tr><td>{ico}{c["nombre"]}</td><td>{_fm(c["presupuesto_diario"], cfg)}</td>'
                  f'<td>{_fm(c["gasto"], cfg)}</td>'
                  f'<td style="text-align:right;">{_resultado(c):,.0f}</td><td>{_costo(c)}</td></tr>')
    tabla = (f'<table class="dt"><tr><th>Campaña</th><th>Presup./día</th><th>Gasto</th>'
             f'<th>{res_col}</th><th>{cost_col}</th></tr>{filas}</table>') if filas else ""

    return _card(f"📣 Marketing — {fuente} (últimos {p['dias']} días)",
                 _kpis(rows) + tabla)


def renderizar_marketing_pagina(data: dict, cfg: dict, titulo: str = "Marketing") -> str:
    """Página HTML standalone (documento completo) con la sección de marketing.
    Útil para generar un dashboard de marketing independiente por tenant."""
    p = data.get("periodo", {})
    card = renderizar_marketing_html(data, cfg)
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
    filas = ""
    if grupo in ("Leads", "Ventas"):
        cols = ("<th>Campaña</th><th>Inversión</th><th>Mensajes</th>"
                "<th>Costo x mensaje</th><th>Conversiones</th>")
        for c in camps:
            cm = _fm(_div(c["gasto"], c["mensajes"]), cfg) if c["mensajes"] else "—"
            filas += (f'<tr><td>{c["nombre"]}</td><td>{_fm(c["gasto"], cfg)}</td>'
                      f'<td style="text-align:right;">{_num(c["mensajes"])}</td><td>{cm}</td>'
                      f'<td style="text-align:right;">{_num(c["leads"])}</td></tr>')
    elif grupo == "Tráfico":
        cols = ("<th>Campaña</th><th>Inversión</th><th>Reproducciones</th>"
                "<th>Visitas al perfil</th><th>Costo x visita</th>")
        for c in camps:
            cv = _fm(_div(c["gasto"], c["visitas_perfil"]), cfg) if c["visitas_perfil"] else "—"
            filas += (f'<tr><td>{c["nombre"]}</td><td>{_fm(c["gasto"], cfg)}</td>'
                      f'<td style="text-align:right;">{_num(c["reproducciones"])}</td>'
                      f'<td style="text-align:right;">{_num(c["visitas_perfil"])}</td><td>{cv}</td></tr>')
    else:  # Interacción, Reconocimiento, Otras
        cols = ("<th>Campaña</th><th>Inversión</th><th>Impresiones</th>"
                "<th>Interacciones</th><th>Clics</th>")
        for c in camps:
            filas += (f'<tr><td>{c["nombre"]}</td><td>{_fm(c["gasto"], cfg)}</td>'
                      f'<td style="text-align:right;">{_num(c["impresiones"])}</td>'
                      f'<td style="text-align:right;">{_num(c["interacciones"])}</td>'
                      f'<td style="text-align:right;">{_num(c["clics"])}</td></tr>')
    return _card(f"Campañas de {grupo} · inversión {_fm(total_g, cfg)}",
                 f'<table class="dt"><tr>{cols}</tr>{filas}</table>')


def renderizar_marketing_grafico(data: dict, cfg: dict, titulo: str = "Marketing") -> str:
    r = data["resumen"]; p = data["periodo"]
    serie = data.get("serie_diaria", [])
    n_camp = len([c for c in data["campanas"] if c["gasto"] > 0])

    cards = (
        _kpi_card("Espectadores", _num(r["impresiones"]),
                  r.get("var_impresiones_pct"), [d["impresiones"] for d in serie])
        + _kpi_card("Interacciones", _num(r["interacciones"]),
                    r.get("var_interacciones_pct"), [d["interacciones"] for d in serie])
        + _kpi_card("Clics en el enlace", _num(r["clics"]),
                    r.get("var_clics_pct"), [d["clics"] for d in serie])
        + _kpi_card("Conversaciones con mensajes iniciadas", _num(r["mensajes"]),
                    r.get("var_mensajes_pct"), [d["mensajes"] for d in serie])
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
<div class="foot">Datos de Meta Ads almacenados en PostgreSQL · generado automáticamente.</div>
</div></body></html>"""
