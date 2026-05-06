from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import config
from ..agents.alertas import calcular_kpis, evaluar_umbrales, renderizar_reporte
from ..auth import get_role

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/alertas")
async def agente_alertas(
    periodo_dias: int = Query(7, ge=1, le=90, description="Días hacia atrás para calcular KPIs"),
    formato:      str = Query("json", description="json | markdown | discord_payload"),
    _rol:         str = Depends(get_role),
):
    """
    Agente 8 — Indicadores y Alertas Tempranas.

    Calcula KPIs sin LLM (SQL puro) y evalúa los umbrales de config.yaml.

    - **json**: estructura completa con kpis, alertas y reporte
    - **markdown**: reporte listo para leer o guardar
    - **discord_payload**: JSON listo para POST a un webhook de Discord
    """
    kpis    = await calcular_kpis(periodo_dias)
    alertas = evaluar_umbrales(kpis, config.CONFIG)
    reporte = renderizar_reporte(kpis, alertas, config.CONFIG)

    tiene_critico  = any(a["nivel"] == "critico" for a in alertas)
    estado_general = "critico" if tiene_critico else "alerta" if alertas else "ok"

    if formato == "markdown":
        return PlainTextResponse(content=reporte, media_type="text/markdown; charset=utf-8")

    if formato == "discord_payload":
        return {"content": reporte[:1900]}

    return {
        "alertas_activas": len(alertas),
        "estado_general":  estado_general,
        "kpis":            kpis,
        "alertas":         alertas,
        "reporte_md":      reporte,
    }
