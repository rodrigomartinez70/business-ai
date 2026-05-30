from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import config
from ..agents.alertas import calcular_kpis, evaluar_umbrales, renderizar_reporte, _fmt_kpi
from ..agents.cierre_diario import (
    build_discord_embed_cierre,
    calcular_cierre,
    renderizar_cierre_markdown,
)
from ..agents.control_gastos import (
    build_discord_embed_control_gastos,
    calcular_control_gastos,
    renderizar_control_gastos_markdown,
)
from ..agents.pnl_mensual import (
    build_discord_embed_pnl,
    calcular_pnl,
    renderizar_pnl_markdown,
)
from ..auth import get_role

router = APIRouter(prefix="/api/agents", tags=["agents"])

# Colores Discord (decimal)
_COLOR_OK      = 0x2ECC71   # verde
_COLOR_ALERTA  = 0xF39C12   # naranja
_COLOR_CRITICO = 0xE74C3C   # rojo


def _build_discord_embed(kpis: list[dict], alertas: list[dict], periodo_dias: int) -> dict:
    tiene_critico = any(a["nivel"] == "critico" for a in alertas)
    biz_name      = config.biz("name", "Negocio")
    fecha_fin     = date.today()
    fecha_inicio  = fecha_fin - timedelta(days=periodo_dias - 1)

    if tiene_critico:
        icono, color, estado = "🚨", _COLOR_CRITICO, "CRÍTICO"
    elif alertas:
        icono, color, estado = "⚠️", _COLOR_ALERTA, "ALERTA"
    else:
        icono, color, estado = "✅", _COLOR_OK, "OK"

    fields = []
    alerta_por_kpi = {a["kpi"]: a for a in alertas}

    for kpi in kpis:
        valor_fmt = _fmt_kpi(kpi, config.CONFIG)
        alerta    = alerta_por_kpi.get(kpi["name"])
        if alerta:
            nivel_icono = "🚨" if alerta["nivel"] == "critico" else "⚠️"
            estado_kpi  = f"{nivel_icono} umbral: {alerta['umbral']}"
        else:
            estado_kpi  = "✅ OK" if kpi.get("valor") is not None else "— sin datos"

        fields.append({
            "name":   kpi["name"],
            "value":  f"**{valor_fmt}**\n{estado_kpi}",
            "inline": True,
        })

    # Separador visual si hay número impar de campos (Discord alinea de a 3)
    if len(fields) % 3 == 2:
        fields.append({"name": "​", "value": "​", "inline": True})

    embed = {
        "title":       f"{icono} KPIs — {biz_name} · {estado}",
        "description": f"📅 {fecha_inicio.strftime('%d/%m')} → {fecha_fin.strftime('%d/%m/%Y')} · últimos {periodo_dias} días",
        "color":       color,
        "fields":      fields,
    }

    if alertas:
        lineas = []
        for a in alertas:
            ni = "🚨" if a["nivel"] == "critico" else "⚠️"
            lineas.append(f"{ni} **{a['kpi']}** — valor: {a['valor']} · umbral: {a['umbral']}")
        embed["footer"] = {"text": "\n".join(lineas)}

    return {"embeds": [embed]}


@router.get("/alertas")
async def agente_alertas(
    periodo_dias: int = Query(7, ge=1, le=90, description="Días hacia atrás para calcular KPIs"),
    formato:      str = Query("json", description="json | markdown | discord_payload"),
    _rol:         str = Depends(get_role),
):
    """
    Agente de Indicadores y Alertas Tempranas.

    Calcula KPIs sin LLM (SQL puro) y evalúa los umbrales de config.yaml.

    - **json**: estructura completa con kpis, alertas y reporte
    - **markdown**: reporte listo para leer o guardar
    - **discord_payload**: embed de Discord listo para POST al webhook
    """
    kpis    = await calcular_kpis(periodo_dias)
    alertas = evaluar_umbrales(kpis)
    reporte = renderizar_reporte(kpis, alertas, config.CONFIG, periodo_dias)

    tiene_critico  = any(a["nivel"] == "critico" for a in alertas)
    estado_general = "critico" if tiene_critico else "alerta" if alertas else "ok"

    if formato == "markdown":
        return PlainTextResponse(content=reporte, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        return _build_discord_embed(kpis, alertas, periodo_dias)

    return {
        "alertas_activas": len(alertas),
        "estado_general":  estado_general,
        "kpis":            kpis,
        "alertas":         alertas,
        "reporte_md":      reporte,
    }


@router.get("/cierre-diario")
async def agente_cierre_diario(
    fecha:   Optional[date] = Query(None, description="Fecha del cierre (default: hoy)"),
    formato: str            = Query("json", description="json | markdown | discord_payload"),
    _rol:    str            = Depends(get_role),
):
    """
    Agente de Cierre Diario.

    Consolida ocupación, movimientos, cobros, ingresos por departamento,
    gastos y GOP del día. Sin LLM — SQL puro.

    - **json**: estructura completa
    - **markdown**: reporte listo para leer
    - **discord_payload**: embed listo para POST al webhook de Discord
    """
    if fecha is None:
        fecha = date.today()

    data = await calcular_cierre(fecha)

    if formato == "markdown":
        md = renderizar_cierre_markdown(data, config.CONFIG)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        return build_discord_embed_cierre(data, config.CONFIG)

    return data


@router.get("/control-gastos")
async def agente_control_gastos(
    fecha_inicio: Optional[date] = Query(None, description="Inicio del período (default: 7 días atrás)"),
    fecha_fin:    Optional[date] = Query(None, description="Fin del período (default: ayer)"),
    formato:      str            = Query("json", description="json | markdown | discord_payload"),
    _rol:         str            = Depends(get_role),
):
    """
    Agente de Control de Gastos.

    Compara gastos del período actual vs el período anterior de igual duración,
    detecta variaciones anómalas por categoría, gastos sin clasificar y
    proveedores que aparecen por primera vez.

    - **json**: estructura completa
    - **markdown**: reporte listo para leer
    - **discord_payload**: embed listo para POST al webhook de Discord
    """
    if fecha_fin is None:
        fecha_fin = date.today() - timedelta(days=1)
    if fecha_inicio is None:
        fecha_inicio = fecha_fin - timedelta(days=6)

    data = await calcular_control_gastos(fecha_inicio, fecha_fin)

    if formato == "markdown":
        md = renderizar_control_gastos_markdown(data, config.CONFIG)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        return build_discord_embed_control_gastos(data, config.CONFIG)

    return data


@router.get("/pnl-mensual")
async def agente_pnl_mensual(
    mes:    int = Query(0,  ge=0, le=12, description="Mes (1-12). 0 = mes anterior."),
    año:    int = Query(0,  ge=0,        description="Año. 0 = año actual."),
    formato: str = Query("json",         description="json | markdown | discord_payload"),
    _rol:   str = Depends(get_role),
):
    """
    Agente de P&L Mensual.

    Estado de resultados completo con comparativa contra mes anterior y
    mismo mes del año pasado. Incluye ocupación, ADR y RevPAR.

    - **json**: estructura completa con los tres períodos
    - **markdown**: informe P&L listo para contabilidad
    - **discord_payload**: embed ejecutivo para el webhook de Discord
    """
    hoy = date.today()
    if año == 0:
        año = hoy.year
    if mes == 0:
        año_cal, mes_cal = (año - 1, 12) if hoy.month == 1 else (año, hoy.month - 1)
    else:
        año_cal, mes_cal = año, mes

    data = await calcular_pnl(año_cal, mes_cal)

    if formato == "markdown":
        md = renderizar_pnl_markdown(data, config.CONFIG)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        return build_discord_embed_pnl(data, config.CONFIG)

    return data
