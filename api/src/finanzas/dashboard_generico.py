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
from src.render import _card, _kpis, _fm, renderizar_ipc_html
from src.finanzas.economia import obtener_ipc
from src.finanzas.control_gastos import calcular_control_gastos
from src.finanzas.conciliacion import calcular_conciliacion
from src.finanzas.pnl import renderizar_pnl_html
from src.finanzas.pnl_plantilla import calcular_desde_plantilla
from src.finanzas import comercial
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


async def calcular_dashboard() -> dict:
    hoy          = date.today()
    desde, corte = _semana_cerrada(hoy)
    cfg          = config.get_config()

    pnl          = await _pnl(cfg, corte)
    gastos       = await calcular_control_gastos(desde, corte)
    conciliacion = await calcular_conciliacion(corte, 30)
    marketing    = await calcular_marketing(corte, 61)     # None si no hay tablas/datos
    ipc          = await obtener_ipc(12)

    comercial_html = (await comercial.render(cfg, _vertical_de(cfg), desde, corte)
                      if comercial.tiene_config(cfg) else None)

    return {
        "fecha_envio":    str(hoy),
        "semana":         {"inicio": str(desde), "fin": str(corte)},
        "pnl":            pnl,
        "gastos":         gastos,
        "conciliacion":   conciliacion,
        "comercial_html": comercial_html,
        "marketing":      marketing,
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


def secciones_html(data: dict, cfg: dict) -> dict:
    """Mismas claves canónicas que un dashboard de vertical; las que no aplican
    (cierre, tributario, estado_dte) se omiten y el Informe las degrada solas.
    Marketing aparece si la empresa tiene datos de marketing (Meta/Google)."""
    mkt = data.get("marketing")
    return {
        "pnl":          _sec_pnl(data["pnl"], cfg),
        "comercial":    data.get("comercial_html") or "",
        "gastos":       _sec_gastos(data["gastos"], cfg),
        "conciliacion": _sec_conciliacion(data.get("conciliacion", {})),
        "marketing":    renderizar_marketing_html(mkt, cfg) if mkt else "",
        "ipc":          renderizar_ipc_html(data.get("ipc")),
    }
