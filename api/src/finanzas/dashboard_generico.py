"""
Dashboard genérico (horizontal) — para empresas sin POS (packs base+erp u otros).

No usa tablas de POS (pedidos/reservas); arma el informe solo con datos
horizontales: P&L (plantilla `cuentas:` del ERP), Gastos, Conciliación,
Ventas/Comercial config-driven e IPC. Las secciones de Liquidez/Cobros/Pagos/
Presupuesto las aporta el panel horizontal (`calcular_panel`) en el Informe.

Lo selecciona `verticals.dispatch.dashboard()` cuando el vertical del tenant no es
uno de los POS conocidos (hotel/restaurante). Expone la misma interfaz que un
dashboard de vertical: `calcular_dashboard()` y `secciones_html(data, cfg)`.
"""

import logging
from datetime import date, timedelta

from src import config
from src.agents._common import to_float
from src.render import _card, _kpis, _fm, _subt, _aviso, renderizar_ipc_html
from src.finanzas.economia import obtener_ipc
from src.finanzas.control_gastos import calcular_control_gastos
from src.finanzas.conciliacion import calcular_conciliacion
from src.finanzas.pnl import renderizar_pnl_html
from src.finanzas.pnl_plantilla import calcular_desde_plantilla
from src.finanzas import comercial
from src.finanzas.tributario import calcular_tributario_semanal
from src.marketing.dashboard import calcular_marketing, renderizar_marketing_html

logger = logging.getLogger(__name__)

# P&L vacío seguro (cuando el tenant no define `pnl.plantilla`): resumen en cero
# para que el resumen ejecutivo del Informe no falle.
_PNL_VACIO = {
    "periodo": {"actual": {"label": ""}, "anterior": {"label": ""}},
    "lineas": [],
    "resumen": {
        "ingresos_netos": 0, "margen_bruto": 0, "margen_bruto_pct": 0,
        "ebitda": 0, "resultado_neto": 0,
        "var_ingresos_pct": None, "var_resultado_pct": None,
    },
}


def _semana_cerrada(hoy: date) -> tuple[date, date]:
    corte = hoy - timedelta(days=hoy.weekday() + 1)   # domingo anterior
    desde = corte - timedelta(days=6)                 # lunes de esa semana
    return desde, corte


def _vertical_de(cfg: dict) -> str:
    return (cfg.get("business") or {}).get("vertical") or "comercial"


async def _pnl(cfg: dict, corte: date) -> dict:
    pnl_cfg = (cfg or {}).get("pnl") or {}
    if pnl_cfg.get("plantilla"):
        return await calcular_desde_plantilla(
            _vertical_de(cfg), pnl_cfg["plantilla"], pnl_cfg.get("constantes", {}), corte)
    return {**_PNL_VACIO}


async def calcular_pnl(hasta: date) -> dict:
    """P&L genérico (plantilla `cuentas:` o vacío). Lo usa `dispatch.pnl()` para
    empresas sin POS (mismo contrato que el agente de P&L de un vertical)."""
    return await _pnl(config.get_config(), hasta)


async def _ingresos_comercial(conn, ini: date, fin: date) -> float:
    """Ingreso afecto de una empresa Comercial: ventas emitidas del RCV (neto).
    Defensivo: 0 si el schema no tiene `clase`/documentos."""
    try:
        v = await conn.fetchval(
            "SELECT COALESCE(SUM(monto_neto), 0) FROM documentos_tributarios "
            "WHERE clase = 'venta' AND fecha BETWEEN $1 AND $2 "
            "AND LOWER(COALESCE(estado,'')) NOT IN "
            "('pendiente_revision','anulado','anulada','rechazado','rechazada')",
            ini, fin)
    except Exception:                                 # noqa: BLE001
        return 0.0
    return to_float(v or 0)


_VALIDO_DTE = ("LOWER(COALESCE(estado,'')) NOT IN "
               "('pendiente_revision','anulado','anulada','rechazado','rechazada')")


async def _ventas_desde_rcv(cfg: dict, desde: date, corte: date) -> str | None:
    """Ventas/Comercial de una empresa sin POS: facturas/boletas emitidas del RCV
    (clase='venta', neto) + variación y top clientes. Devuelve el HTML del card."""
    largo = (corte - desde).days
    ant_fin = desde - timedelta(days=1)
    ant_desde = ant_fin - timedelta(days=largo)
    async with config.db_pool.acquire() as conn:
        try:
            cur = await conn.fetchrow(
                f"SELECT COALESCE(SUM(monto_neto),0) AS neto, COUNT(*) AS n FROM documentos_tributarios "
                f"WHERE clase='venta' AND fecha BETWEEN $1 AND $2 AND {_VALIDO_DTE}", desde, corte)
            tp = await conn.fetchval(
                f"SELECT COALESCE(SUM(monto_neto),0) FROM documentos_tributarios "
                f"WHERE clase='venta' AND fecha BETWEEN $1 AND $2 AND {_VALIDO_DTE}", ant_desde, ant_fin)
            top = await conn.fetch(
                f"SELECT COALESCE(NULLIF(TRIM(proveedor),''),'—') AS cliente, SUM(monto_neto) AS m "
                f"FROM documentos_tributarios WHERE clase='venta' AND fecha BETWEEN $1 AND $2 AND {_VALIDO_DTE} "
                f"GROUP BY 1 ORDER BY 2 DESC LIMIT 5", desde, corte)
        except Exception:                             # noqa: BLE001 — sin clase/tabla
            return None
    neto, n = to_float(cur["neto"]), int(cur["n"] or 0)
    if neto == 0 and n == 0:
        return None
    tp = to_float(tp)
    var = f"{round((neto - tp) * 100 / tp, 1):+.1f}%" if tp > 0 else "—"
    rows = [("Ventas netas (emitidas)", _fm(neto, cfg)),
            ("N° documentos", str(n)),
            ("vs período anterior", var)]
    filas = "".join(f'<tr><td>{r["cliente"]}</td><td>{_fm(to_float(r["m"]), cfg)}</td></tr>' for r in top)
    tabla = (f'<table class="dt"><tr><th>Cliente</th><th>Ventas</th></tr>{filas}</table>') if filas else ""
    return _card("📊 Ventas / Comercial", _kpis(rows) + tabla)


async def _gastos_desde_rcv(desde: date, corte: date) -> dict | None:
    """Control de gastos desde las compras del RCV (facturas recibidas, neto) — para
    empresas sin POS cuyo libro `gastos` está vacío. El SII no categoriza → 'Sin
    clasificar'. Mismo shape que calcular_control_gastos (resumen/categorias/alertas)."""
    largo = (corte - desde).days
    ant_fin = desde - timedelta(days=1)
    ant_desde = ant_fin - timedelta(days=largo)
    async with config.db_pool.acquire() as conn:
        try:
            cats = await conn.fetch(
                "SELECT COALESCE(NULLIF(TRIM(categoria_gasto), ''), 'Sin clasificar') AS categoria, "
                "SUM(monto_neto) AS monto FROM documentos_tributarios "
                "WHERE clase = 'compra' AND fecha BETWEEN $1 AND $2 GROUP BY 1 ORDER BY 2 DESC",
                desde, corte)
            ta = await conn.fetchval("SELECT COALESCE(SUM(monto_neto),0) FROM documentos_tributarios "
                                     "WHERE clase='compra' AND fecha BETWEEN $1 AND $2", desde, corte)
            tp = await conn.fetchval("SELECT COALESCE(SUM(monto_neto),0) FROM documentos_tributarios "
                                     "WHERE clase='compra' AND fecha BETWEEN $1 AND $2", ant_desde, ant_fin)
        except Exception:                             # noqa: BLE001 — sin clase/tabla
            return None
    ta, tp = to_float(ta), to_float(tp)
    if ta == 0 and not cats:
        return None
    var = round((ta - tp) * 100 / tp, 1) if tp > 0 else None
    return {
        "resumen": {"total_actual": ta, "total_anterior": tp, "variacion_pct": var},
        "categorias": [{"categoria": c["categoria"], "monto_actual": to_float(c["monto"])} for c in cats],
        "alertas": [],
        "fuente": "rcv",
    }


async def calcular_dashboard() -> dict:
    hoy          = date.today()
    desde, corte = _semana_cerrada(hoy)
    cfg          = config.get_config()

    pnl          = await _pnl(cfg, corte)
    gastos       = await calcular_control_gastos(desde, corte)
    if not gastos.get("resumen", {}).get("total_actual"):     # libro `gastos` vacío
        gastos = await _gastos_desde_rcv(desde, corte) or gastos
    conciliacion = await calcular_conciliacion(corte, 30)
    marketing    = await calcular_marketing(corte, 61)     # None si no hay tablas/datos
    tributario   = await calcular_tributario_semanal(hoy, _ingresos_comercial)   # F29 mes a la fecha
    ipc          = await obtener_ipc(12)

    comercial_html = (await comercial.render(cfg, _vertical_de(cfg), desde, corte)
                      if comercial.tiene_config(cfg)
                      else await _ventas_desde_rcv(cfg, desde, corte))   # sin POS → RCV

    return {
        "fecha_envio":    str(hoy),
        "semana":         {"inicio": str(desde), "fin": str(corte)},
        "pnl":            pnl,
        "gastos":         gastos,
        "conciliacion":   conciliacion,
        "comercial_html": comercial_html,
        "marketing":      marketing,
        "tributario":     tributario,
        "ipc":            ipc,
    }


# ── Secciones (horizontales) ─────────────────────────────────

def _sec_pnl(p: dict, cfg) -> str:
    if not p or not p.get("lineas"):
        return ""
    return _card("📑 P&L — Estado de Resultados (comparativo YTD)",
                 renderizar_pnl_html(p, cfg))


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
        filas += f'<tr><td>{c["categoria"]}</td><td>{_fm(c["monto_actual"], cfg)}</td></tr>'
    tabla = (f'<table class="dt"><tr><th>Categoría</th><th>Monto</th></tr>{filas}</table>'
             if filas else "")
    return _card("📋 Control de Gastos", _kpis(rows) + tabla)


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


def _sec_tributario(trib: dict) -> str:
    """Copiloto Tributario / F29 (horizontal). El IVA débito/crédito sale de los DTE
    del RCV (clase venta/compra) cargados en documentos_tributarios."""
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


def secciones_html(data: dict, cfg: dict) -> dict:
    """Mismas claves canónicas que un dashboard de vertical; las que no aplican
    (cierre, estado_dte) se omiten y el Informe las degrada solas. Marketing y
    Tributario aparecen si la empresa tiene datos (mkt / DTE del RCV)."""
    mkt = data.get("marketing")
    return {
        "pnl":          _sec_pnl(data["pnl"], cfg),
        "comercial":    data.get("comercial_html") or "",
        "gastos":       _sec_gastos(data["gastos"], cfg),
        "conciliacion": _sec_conciliacion(data.get("conciliacion", {})),
        "marketing":    renderizar_marketing_html(mkt, cfg) if mkt else "",
        "tributario":   _sec_tributario(data.get("tributario", {})),
        "ipc":          renderizar_ipc_html(data.get("ipc")),
    }
