from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import config
from ..agents.alertas import calcular_kpis, evaluar_umbrales, renderizar_reporte, _fmt_kpi
from ..agents.insights import generar_insights
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
from ..agents.rentabilidad_canal import (
    build_discord_embed_rentabilidad_canal,
    calcular_rentabilidad_canal,
    renderizar_rentabilidad_canal_markdown,
)
from ..agents.cash_flow import (
    build_discord_embed_cash_flow,
    calcular_cash_flow,
    renderizar_cash_flow_markdown,
)
from ..agents.revenue_management import (
    build_discord_embed_revenue,
    calcular_revenue_management,
    renderizar_revenue_markdown,
)
from ..auth import get_role

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _adjuntar_insights(embed_payload: dict, insights: list[str]) -> dict:
    """Agrega el campo de insights IA al primer embed del payload, si hay insights."""
    if not insights or not embed_payload.get("embeds"):
        return embed_payload
    texto = "\n".join(f"• {i}" for i in insights)
    embed_payload["embeds"][0]["fields"].append({
        "name":   "💡 Insights IA",
        "value":  texto,
        "inline": False,
    })
    return embed_payload

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
        data_alertas = {"kpis": kpis, "alertas": alertas, "estado_general": estado_general}
        insights = await generar_insights("alertas", data_alertas)
        return _adjuntar_insights(_build_discord_embed(kpis, alertas, periodo_dias), insights)

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
        insights = await generar_insights("cierre_diario", data)
        return _adjuntar_insights(build_discord_embed_cierre(data, config.CONFIG), insights)

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
        insights = await generar_insights("control_gastos", data)
        return _adjuntar_insights(build_discord_embed_control_gastos(data, config.CONFIG), insights)

    return data


@router.get("/pnl-mensual")
async def agente_pnl_mensual(
    mes:    int = Query(0,  ge=0, le=12, description="Mes (1-12). 0 = mes anterior."),
    anio:   int = Query(0,  ge=0,        description="Año. 0 = año actual."),
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
    if anio == 0:
        anio = hoy.year
    if mes == 0:
        año_cal, mes_cal = (anio - 1, 12) if hoy.month == 1 else (anio, hoy.month - 1)
    else:
        año_cal, mes_cal = anio, mes

    data = await calcular_pnl(año_cal, mes_cal)

    if formato == "markdown":
        md = renderizar_pnl_markdown(data, config.CONFIG)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        insights = await generar_insights("pnl_mensual", data)
        return _adjuntar_insights(build_discord_embed_pnl(data, config.CONFIG), insights)

    return data


@router.get("/revenue-management")
async def agente_revenue_management(
    horizon_dias: int = Query(30, ge=7, le=90, description="Días de proyección hacia adelante"),
    formato:      str = Query("json", description="json | markdown | discord_payload"),
    _rol:         str = Depends(get_role),
):
    """
    Agente de Revenue Management.

    Muestra ocupación actual, ADR y RevPAR del día, tendencia de los últimos
    7 y 30 días, proyección de ocupación para los próximos N días, performance
    por canal y oportunidades de precio (días con alta demanda y tarifa baja).
    """
    data = await calcular_revenue_management(horizon_dias)

    if formato == "markdown":
        md = renderizar_revenue_markdown(data, config.CONFIG)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        insights = await generar_insights("revenue_management", data)
        return _adjuntar_insights(build_discord_embed_revenue(data, config.CONFIG), insights)

    return data


@router.get("/cash-flow")
async def agente_cash_flow(
    formato: str = Query("json", description="json | markdown | discord_payload"),
    _rol:    str = Depends(get_role),
):
    """
    Agente de Cash Flow.

    Proyecta ingresos esperados (reservas confirmadas futuras, por fecha de checkout)
    vs gastos estimados (promedio histórico semanal de las últimas 12 semanas)
    para las próximas 8 semanas. Incluye cobros pendientes y semáforo de liquidez.
    """
    data = await calcular_cash_flow()

    if formato == "markdown":
        md = renderizar_cash_flow_markdown(data, config.CONFIG)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        insights = await generar_insights("cash_flow", data)
        return _adjuntar_insights(build_discord_embed_cash_flow(data, config.CONFIG), insights)

    return data


@router.get("/rentabilidad-canal")
async def agente_rentabilidad_canal(
    mes:    int = Query(0, ge=0, le=12, description="Mes (1-12). 0 = mes anterior."),
    anio:   int = Query(0, ge=0,        description="Año. 0 = año actual."),
    formato: str = Query("json",        description="json | markdown | discord_payload"),
    _rol:   str = Depends(get_role),
):
    """
    Agente de Rentabilidad por Canal.

    Ranking de canales de venta por ingreso neto real (descontando comisión OTA),
    tasa de cancelación y ADR. Comparativa contra mismo período del año anterior.
    Identifica el canal más rentable y el más confiable.
    """
    hoy = date.today()
    if anio == 0:
        anio = hoy.year
    if mes == 0:
        año_cal, mes_cal = (anio - 1, 12) if hoy.month == 1 else (anio, hoy.month - 1)
    else:
        año_cal, mes_cal = anio, mes

    data = await calcular_rentabilidad_canal(año_cal, mes_cal)

    if formato == "markdown":
        md = renderizar_rentabilidad_canal_markdown(data, config.CONFIG)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        insights = await generar_insights("rentabilidad_canal", data)
        return _adjuntar_insights(build_discord_embed_rentabilidad_canal(data, config.CONFIG), insights)

    return data
