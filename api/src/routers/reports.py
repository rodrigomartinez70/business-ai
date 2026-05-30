from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from .. import config
from ..agent import ejecutar_plan, ejecutar_sql, generar_plan, generar_sql, sintetizar_local
from ..audit import generar_reporte_uso, renderizar_uso_markdown
from ..auth import get_role
from ..formatting import formatear_respuesta

router = APIRouter(prefix="/api/report", tags=["reports"])


@router.get("/usage")
async def reporte_uso(
    fecha_inicio: Optional[date] = None,
    fecha_fin:    Optional[date] = None,
    formato:      str = "json",
    page:         int = Query(1,  ge=1,            description="Página de consultas_recientes"),
    page_size:    int = Query(20, ge=1, le=100,    description="Registros por página (máx 100)"),
    _rol:         str = Depends(get_role),
):
    """Reporte de uso e interacciones del agente (últimos 30 días por defecto)."""
    if not fecha_fin:
        fecha_fin = date.today()
    if not fecha_inicio:
        fecha_inicio = fecha_fin - timedelta(days=29)

    reporte = await generar_reporte_uso(fecha_inicio, fecha_fin, page=page, page_size=page_size)

    if formato == "markdown":
        md = renderizar_uso_markdown(reporte, config.biz("name", "Negocio"))
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return reporte


@router.get("/weekly")
async def reporte_semanal(
    fecha_inicio: Optional[date] = None,
    fecha_fin:    Optional[date] = None,
    dias:         Optional[int]  = Query(None, ge=1, le=365, description="Últimos N días (alternativa a fecha_inicio/fecha_fin)"),
    formato:      str = "markdown",
    rol:          str = Depends(get_role),
):
    """Reporte ejecutivo del negocio generado via pipeline LLM (schema-agnostic)."""
    if not fecha_fin:
        fecha_fin = date.today()
    if not fecha_inicio:
        fecha_inicio = fecha_fin - timedelta(days=(dias - 1) if dias else 6)

    biz_name = config.biz("name", "Negocio")
    pregunta = (
        f"Genera un reporte ejecutivo completo de {biz_name} "
        f"para el período del {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}. "
        f"Incluye: ingresos totales y desglose por categorías, gastos y su distribución, "
        f"resultado operativo (GOP/margen si aplica), y las principales métricas del período. "
        f"Formatea la respuesta en markdown con tablas y secciones claras."
    )

    pasos = await generar_plan(pregunta, rol)

    if pasos:
        resultados = await ejecutar_plan(pasos, rol, pregunta)
        reporte    = await sintetizar_local(pregunta, resultados)
    else:
        sql, _  = await generar_sql(pregunta, rol)
        datos   = await ejecutar_sql(sql, rol, pregunta)
        reporte = formatear_respuesta(datos)

    encabezado = "\n".join([
        f"# Reporte — {biz_name}",
        f"**Período:** {fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}",
        f"**Generado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "", "---", "",
    ])

    contenido = encabezado + reporte

    if formato == "json":
        return {"periodo": {"inicio": str(fecha_inicio), "fin": str(fecha_fin)}, "reporte": contenido}
    return PlainTextResponse(content=contenido, media_type="text/markdown; charset=utf-8")
