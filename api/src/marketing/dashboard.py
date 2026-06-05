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
from src.render import _card, _kpis, _fm, _aviso

logger = logging.getLogger(__name__)


def _div(a: float, b: float) -> float:
    return (a / b) if b else 0.0


async def calcular_marketing(hasta: date, dias: int = 61) -> dict | None:
    desde     = hasta - timedelta(days=dias - 1)
    ant_hasta = desde - timedelta(days=1)
    ant_desde = ant_hasta - timedelta(days=dias - 1)

    try:
        async with config.db_pool.acquire() as conn:
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
                SELECT COALESCE(SUM(gasto),0) AS gasto, COALESCE(SUM(conversiones),0) AS leads
                  FROM insights_marketing WHERE fecha BETWEEN $1 AND $2
            """, ant_desde, ant_hasta)

            camp = await conn.fetch("""
                SELECT c.nombre, c.estado, c.presupuesto_diario,
                       COALESCE(SUM(i.gasto),0)        AS gasto,
                       COALESCE(SUM(i.conversiones),0) AS leads,
                       COALESCE(SUM(i.clics),0)        AS clics
                  FROM campanas c
                  LEFT JOIN insights_marketing i
                         ON i.campana_id = c.id AND i.fecha BETWEEN $1 AND $2
                 GROUP BY c.id, c.nombre, c.estado, c.presupuesto_diario
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

    resumen = {
        "inversion": gasto,
        "leads": leads,
        "cpl": _div(gasto, leads),
        "cpc": _div(gasto, clics),
        "ctr": _div(clics, impresiones) * 100,
        "cpm": _div(gasto, impresiones) * 1000,
        "alcance": alcance,
        "conversion_clic_lead": _div(leads, clics) * 100,
        "var_inversion_pct": (_div(gasto - g_ant, g_ant) * 100) if g_ant else None,
        "var_leads_pct":     (_div(leads - l_ant, l_ant) * 100) if l_ant else None,
    }

    campanas: list[dict] = []
    alertas: list[dict] = []
    for c in camp:
        g = float(c["gasto"]); l = float(c["leads"])
        campanas.append({"nombre": c["nombre"], "estado": c["estado"],
                         "gasto": g, "leads": l, "cpl": _div(g, l), "clics": int(c["clics"])})
        if c["estado"] == "PAUSED" and (c["presupuesto_diario"] or 0) > 0:
            alertas.append({"nivel": "info", "titulo": f"Campaña pausada con presupuesto: {c['nombre']}",
                            "desc": "Tiene presupuesto asignado pero está en pausa."})
        if g > 0 and l == 0:
            alertas.append({"nivel": "alerta", "titulo": f"Gasto sin leads: {c['nombre']}",
                            "desc": "La campaña gastó sin generar conversiones en el período."})

    activas = [c for c in campanas if c["leads"] > 0]
    mejor = min(activas, key=lambda c: c["cpl"]) if activas else None
    peor  = max(activas, key=lambda c: c["cpl"]) if activas else None

    return {
        "periodo": {"desde": str(desde), "hasta": str(hasta), "dias": dias},
        "resumen": resumen,
        "campanas": campanas,
        "alertas": alertas,
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
