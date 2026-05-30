from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import config
from ..agents.alertas import calcular_kpis, evaluar_umbrales, renderizar_reporte, _fmt_kpi
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
