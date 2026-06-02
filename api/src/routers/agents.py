from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Body
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .. import config
from ..agents.alertas import calcular_kpis, evaluar_umbrales, renderizar_reporte, _fmt_kpi
from ..agents.insights import generar_insights
from ..verticals.hotel.agents.cierre_diario import (
    calcular_cierre,
    renderizar_cierre_markdown,
)
from ..verticals.hotel.agents.control_gastos import (
    calcular_control_gastos,
    renderizar_control_gastos_markdown,
)
from ..verticals.hotel.agents.pnl_mensual import (
    calcular_pnl,
    renderizar_pnl_markdown,
)
from ..verticals.hotel.agents.rentabilidad_canal import (
    calcular_rentabilidad_canal,
    renderizar_rentabilidad_canal_markdown,
)
from ..verticals.hotel.agents.cash_flow import (
    calcular_cash_flow,
    renderizar_cash_flow_markdown,
)
from ..verticals.hotel.agents.revenue_management import (
    calcular_revenue_management,
    renderizar_revenue_markdown,
)
from ..auth import get_role
from ..verticals.hotel.dashboard import calcular_dashboard, renderizar_dashboard_html
from ..verticals.hotel.agents.tributario import (
    calcular_tributario_semanal,
    renderizar_tributario_markdown,
)
from ..delivery import enviar_dashboard_email

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/alertas")
async def agente_alertas(
    periodo_dias: int = Query(7, ge=1, le=90, description="Días hacia atrás para calcular KPIs"),
    formato:      str = Query("json", description="json | markdown"),
    _rol:         str = Depends(get_role),
):
    """
    Agente de Indicadores y Alertas Tempranas.

    Calcula KPIs sin LLM (SQL puro) y evalúa los umbrales de config.yaml.

    - **json**: estructura completa con kpis, alertas y reporte
    - **markdown**: reporte listo para leer o guardar
    """
    kpis    = await calcular_kpis(periodo_dias)
    alertas = evaluar_umbrales(kpis)
    reporte = renderizar_reporte(kpis, alertas, config.get_config(), periodo_dias)

    tiene_critico  = any(a["nivel"] == "critico" for a in alertas)
    estado_general = "critico" if tiene_critico else "alerta" if alertas else "ok"

    if formato == "markdown":
        return PlainTextResponse(content=reporte, media_type="text/markdown; charset=utf-8")

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
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    Agente de Cierre Diario.

    Consolida ocupación, movimientos, cobros, ingresos por departamento,
    gastos y GOP del día. Sin LLM — SQL puro.

    - **json**: estructura completa
    - **markdown**: reporte listo para leer
    """
    if fecha is None:
        fecha = date.today()

    data = await calcular_cierre(fecha)

    if formato == "markdown":
        md = renderizar_cierre_markdown(data, config.get_config())
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/control-gastos")
async def agente_control_gastos(
    fecha_inicio: Optional[date] = Query(None, description="Inicio del período (default: 7 días atrás)"),
    fecha_fin:    Optional[date] = Query(None, description="Fin del período (default: ayer)"),
    formato:      str            = Query("json", description="json | markdown"),
    _rol:         str            = Depends(get_role),
):
    """
    Agente de Control de Gastos.

    Compara gastos del período actual vs el período anterior de igual duración,
    detecta variaciones anómalas por categoría, gastos sin clasificar y
    proveedores que aparecen por primera vez.

    - **json**: estructura completa
    - **markdown**: reporte listo para leer
    """
    if fecha_fin is None:
        fecha_fin = date.today() - timedelta(days=1)
    if fecha_inicio is None:
        fecha_inicio = fecha_fin - timedelta(days=6)

    data = await calcular_control_gastos(fecha_inicio, fecha_fin)

    if formato == "markdown":
        md = renderizar_control_gastos_markdown(data, config.get_config())
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/pnl-mensual")
async def agente_pnl_mensual(
    mes:    int = Query(0,  ge=0, le=12, description="Mes (1-12). 0 = mes anterior."),
    anio:   int = Query(0,  ge=0,        description="Año. 0 = año actual."),
    formato: str = Query("json",         description="json | markdown"),
    _rol:   str = Depends(get_role),
):
    """
    Agente de P&L Mensual.

    Estado de resultados completo con comparativa contra mes anterior y
    mismo mes del año pasado. Incluye ocupación, ADR y RevPAR.

    - **json**: estructura completa con los tres períodos
    - **markdown**: informe P&L listo para contabilidad
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
        md = renderizar_pnl_markdown(data, config.get_config())
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/revenue-management")
async def agente_revenue_management(
    horizon_dias: int = Query(30, ge=7, le=90, description="Días de proyección hacia adelante"),
    formato:      str = Query("json", description="json | markdown"),
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
        md = renderizar_revenue_markdown(data, config.get_config())
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/cash-flow")
async def agente_cash_flow(
    formato: str = Query("json", description="json | markdown"),
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
        md = renderizar_cash_flow_markdown(data, config.get_config())
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/rentabilidad-canal")
async def agente_rentabilidad_canal(
    mes:    int = Query(0, ge=0, le=12, description="Mes (1-12). 0 = mes anterior."),
    anio:   int = Query(0, ge=0,        description="Año. 0 = año actual."),
    formato: str = Query("json",        description="json | markdown"),
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
        md = renderizar_rentabilidad_canal_markdown(data, config.get_config())
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/dashboard-semanal")
async def agente_dashboard_semanal(
    formato: str = Query("html", description="html | email | json"),
    _rol:    str = Depends(get_role),
):
    """
    Dashboard semanal consolidado (lunes).

    Reúne P&L YTD, Cash Flow, Rentabilidad por canal (mes en curso), Revenue,
    Control de Gastos y el cierre de la última semana en un único HTML tipo
    dashboard, con los problemas destacados arriba.

    - **html**: devuelve el dashboard renderizado (para previsualizar)
    - **email**: genera y envía el dashboard por correo (SMTP)
    - **json**: estructura completa de datos (sin render)
    """
    data = await calcular_dashboard()

    if formato == "json":
        return data

    html = renderizar_dashboard_html(data, config.get_config())

    if formato == "email":
        resultado = enviar_dashboard_email(html, config.get_config())
        return resultado

    return PlainTextResponse(content=html, media_type="text/html; charset=utf-8")


@router.get("/tributario")
async def agente_tributario(
    fecha:   Optional[date] = Query(None, description="Fecha de corte (default: hoy)"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    Copiloto Tributario — agentes IVA, Cumplimiento y Riesgo.

    - **Agente IVA**: débito, crédito, saldo, proyección y F29.
    - **Agente Cumplimiento**: calendario tributario, DJs y próximos vencimientos.
    - **Agente Riesgo**: inconsistencias, fiscalización y alertas.

    - **json**: estructura completa de los tres agentes.
    - **markdown**: reporte listo para leer.
    """
    corte = fecha or date.today()
    data  = await calcular_tributario_semanal(corte)

    if formato == "markdown":
        md = renderizar_tributario_markdown(data)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


# ─────────────────────────────────────────────────────────────
# Gestión de Documentos Tributarios (IVA)
# ─────────────────────────────────────────────────────────────

class DocumentoTributario(BaseModel):
    fecha: date
    tipo: str = "factura"
    numero_documento: Optional[str] = None
    proveedor: str
    monto_neto: float
    categoria_gasto: Optional[str] = None
    observaciones: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "fecha": "2026-06-02",
                "tipo": "factura",
                "numero_documento": "F-001",
                "proveedor": "Nombre Proveedor",
                "monto_neto": 1000.00,
                "categoria_gasto": "servicios",
                "observaciones": "Descripción del gasto"
            }
        }


@router.post("/tributario/documentos")
async def agregar_documento_tributario(
    doc: DocumentoTributario = Body(...),
    _rol: str = Depends(get_role),
):
    """Agregar un documento tributario pendiente de procesar (factura, boleta, etc)."""
    # Calcular IVA (19% si no es exenta)
    monto_iva = round(doc.monto_neto * 0.19, 2) if doc.tipo != "factura_exenta" else 0
    monto_total = doc.monto_neto + monto_iva

    async with config.db_pool.acquire() as conn:
        resultado = await conn.fetchrow("""
            INSERT INTO documentos_tributarios
            (fecha, tipo, numero_documento, proveedor, monto_neto, monto_iva, monto_total, categoria_gasto, observaciones)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
        """, doc.fecha, doc.tipo, doc.numero_documento, doc.proveedor,
            doc.monto_neto, monto_iva, monto_total, doc.categoria_gasto, doc.observaciones)

    return {
        "id": resultado["id"],
        "proveedor": doc.proveedor,
        "monto_neto": float(doc.monto_neto),
        "monto_iva": float(monto_iva),
        "monto_total": float(monto_total),
        "estado": "pendiente_revision",
    }


@router.get("/tributario/documentos")
async def listar_documentos_tributarios(
    estado: Optional[str] = Query(None, description="pendiente_revision | registrado | rechazado"),
    _rol: str = Depends(get_role),
):
    """Listar documentos tributarios (filtrar por estado si se proporciona)."""
    async with config.db_pool.acquire() as conn:
        query = "SELECT id, fecha, tipo, numero_documento, proveedor, monto_neto, monto_iva, monto_total, estado FROM documentos_tributarios"
        params = []
        if estado:
            query += " WHERE estado = $1"
            params = [estado]
        query += " ORDER BY fecha DESC"

        documentos = await conn.fetch(query, *params)

    return {
        "total": len(documentos),
        "documentos": [
            {
                "id": d["id"],
                "fecha": str(d["fecha"]),
                "tipo": d["tipo"],
                "numero_documento": d["numero_documento"],
                "proveedor": d["proveedor"],
                "monto_neto": float(d["monto_neto"]),
                "monto_iva": float(d["monto_iva"]),
                "monto_total": float(d["monto_total"]),
                "estado": d["estado"],
            }
            for d in documentos
        ]
    }


@router.patch("/tributario/documentos/{doc_id}")
async def actualizar_documento(
    doc_id: int,
    nuevo_estado: str = Body(..., embed=True, description="pendiente_revision | registrado | rechazado"),
    _rol: str = Depends(get_role),
):
    """Cambiar el estado de un documento (marcar como registrado o rechazado)."""
    async with config.db_pool.acquire() as conn:
        resultado = await conn.fetchrow("""
            UPDATE documentos_tributarios
            SET estado = $1, updated_at = CURRENT_TIMESTAMP
            WHERE id = $2
            RETURNING id, estado, monto_iva
        """, nuevo_estado, doc_id)

        if not resultado:
            return {"error": "Documento no encontrado", "doc_id": doc_id}

    return {
        "id": resultado["id"],
        "estado": resultado["estado"],
        "iva_procesado": float(resultado["monto_iva"]) if nuevo_estado == "registrado" else 0,
    }
