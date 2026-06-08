from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Body
from fastapi.responses import PlainTextResponse, HTMLResponse
from pydantic import BaseModel

from .. import config
from ..agents.alertas import calcular_kpis, evaluar_umbrales, renderizar_reporte, _fmt_kpi
from ..agents.insights import generar_insights
from ..verticals.hotel.agents.cierre_diario import (
    calcular_cierre,
    renderizar_cierre_markdown,
)
from ..finanzas.control_gastos import (
    calcular_control_gastos,
    renderizar_control_gastos_markdown,
)
from ..finanzas.cuentas_por_pagar import calcular_cuentas_por_pagar, renderizar_cxp_markdown
from ..finanzas.cuentas_por_cobrar import calcular_cuentas_por_cobrar, renderizar_cxc_markdown
from ..finanzas.presupuesto import calcular_presupuesto, renderizar_presupuesto_markdown
from ..finanzas.tesoreria import calcular_tesoreria, renderizar_tesoreria_markdown
from ..finanzas.cfo import calcular_cfo, renderizar_cfo_markdown
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
from ..auth import get_role, get_tenant_ctx_web
from ..marketing.dashboard import calcular_marketing, renderizar_marketing_grafico
from ..verticals import dispatch
from ..delivery import enviar_dashboard_email

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/marketing")
async def agente_marketing(
    dias:    int = Query(60, ge=1, le=365, description="Tamaño de ventana en días (compara vs ventana previa)"),
    formato: str = Query("html", description="html | json"),
    _ctx=Depends(get_tenant_ctx_web),
):
    """
    Dashboard de Marketing (HORIZONTAL) — estilo "Resumen de publicidad" de Meta.

    Disponible para cualquier negocio que tenga datos de marketing cargados
    (tablas canales_marketing / campanas / insights_marketing). Compara la ventana
    de `dias` contra la ventana previa de igual tamaño.

    - **html**: página gráfica (tarjetas con sparklines + tablas por objetivo).
      Abrible en el navegador: `/api/agents/marketing?formato=html&key=<API_KEY>`
    - **json**: estructura completa de métricas.
    """
    data = await calcular_marketing(date.today(), dias)
    if not data:
        if formato == "json":
            return {"disponible": False,
                    "mensaje": "Este negocio no tiene datos de marketing cargados."}
        return HTMLResponse(
            '<div style="font-family:sans-serif;padding:40px;color:#374151;">'
            '<h2>Sin datos de marketing</h2><p>Este negocio todavía no tiene una '
            'integración de marketing (ej. Meta Ads) con datos cargados.</p></div>',
            status_code=200)

    if formato == "json":
        return data

    cfg = config.get_config()
    biz = cfg.get("business", {}).get("name", "Negocio")
    return HTMLResponse(content=renderizar_marketing_grafico(data, cfg, biz))


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


@router.get("/pnl")
async def agente_pnl(
    fecha:   Optional[date] = Query(None, description="Corte YTD (default: hoy)"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    P&L — Estado de Resultados comparativo.

    Año actual YTD (1-ene → corte) vs año anterior en el mismo rango, con
    variación absoluta y porcentual. Estructura financiera estándar, genérica
    por vertical (los ingresos/costo de ventas los aporta cada rubro).

    - **json**: estructura completa (líneas + resumen).
    - **markdown**: informe P&L listo para contabilidad.
    """
    corte = fecha or date.today()
    mod   = dispatch.pnl()
    data  = await mod.calcular_pnl(corte)

    if formato == "markdown":
        md = mod.renderizar_pnl_markdown(data, config.get_config())
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
    mod  = dispatch.dashboard()
    data = await mod.calcular_dashboard()

    if formato == "json":
        return data

    html = mod.renderizar_dashboard_html(data, config.get_config())

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
    mod   = dispatch.tributario()
    data  = await mod.calcular_tributario_semanal(corte)

    if formato == "markdown":
        md = mod.renderizar_tributario_markdown(data)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/conciliacion")
async def agente_conciliacion(
    fecha:   Optional[date] = Query(None, description="Fecha de corte (default: hoy)"),
    dias:    int            = Query(30, ge=1, le=90, description="Ventana a conciliar"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    Agente Conciliación bancaria.

    Cruza la cartola cargada (movimientos_bancarios) contra pagos, gastos y
    documentos tributarios, y reporta el % conciliado y las excepciones.
    El agente no se conecta al banco: solo lee la cartola que subiste por CSV.
    """
    corte = fecha or date.today()
    mod   = dispatch.conciliacion()
    data  = await mod.calcular_conciliacion(corte, dias)

    if formato == "markdown":
        md = mod.renderizar_conciliacion_markdown(data)
        return PlainTextResponse(content=md, media_type="text/markdown; charset=utf-8")

    return data


@router.get("/cuentas-por-pagar")
async def agente_cuentas_por_pagar(
    fecha:   Optional[date] = Query(None, description="Fecha de corte (default: hoy)"),
    plazo:   int            = Query(30, ge=1, le=180, description="Plazo de vencimiento estimado (días)"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    Agente Cuentas por Pagar — facturas de compra pendientes, aging, vencidas y
    ranking por proveedor. Vencimiento estimado = fecha del documento + `plazo`.
    """
    data = await calcular_cuentas_por_pagar(fecha or date.today(), plazo)
    if formato == "markdown":
        return PlainTextResponse(content=renderizar_cxp_markdown(data),
                                 media_type="text/markdown; charset=utf-8")
    return data


@router.get("/cuentas-por-cobrar")
async def agente_cuentas_por_cobrar(
    fecha:   Optional[date] = Query(None, description="Fecha de corte (default: hoy)"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    Agente Cuentas por Cobrar — cartera devengada no cobrada, aging y DSO.
    En negocios de cobro al contado la cartera puede ser cero.
    """
    data = await calcular_cuentas_por_cobrar(fecha or date.today())
    if formato == "markdown":
        return PlainTextResponse(content=renderizar_cxc_markdown(data),
                                 media_type="text/markdown; charset=utf-8")
    return data


@router.get("/presupuesto")
async def agente_presupuesto(
    fecha:   Optional[date] = Query(None, description="Fecha de corte (default: hoy)"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    Agente Presupuestario — presupuesto vs ejecución real (YTD) por categoría,
    con desviaciones. Requiere la tabla `presupuesto` cargada.
    """
    data = await calcular_presupuesto(fecha or date.today())
    if formato == "markdown":
        return PlainTextResponse(content=renderizar_presupuesto_markdown(data),
                                 media_type="text/markdown; charset=utf-8")
    return data


@router.get("/tesoreria")
async def agente_tesoreria(
    fecha:   Optional[date] = Query(None, description="Fecha de corte (default: hoy)"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    Agente Tesorería — posición de caja, forecast de liquidez a 8 semanas y
    propuesta de pagos (qué CxP caben en la caja proyectada). Reemplaza al cash-flow simple.
    """
    data = await calcular_tesoreria(fecha or date.today())
    if formato == "markdown":
        return PlainTextResponse(content=renderizar_tesoreria_markdown(data),
                                 media_type="text/markdown; charset=utf-8")
    return data


@router.get("/cfo")
async def agente_cfo(
    fecha:   Optional[date] = Query(None, description="Fecha de corte (default: hoy)"),
    formato: str            = Query("json", description="json | markdown"),
    _rol:    str            = Depends(get_role),
):
    """
    CFO Virtual — informe ejecutivo que consolida P&L, Tesorería, CxC/CxP,
    Presupuesto y Copiloto Tributario, con semáforos y puntos clave.
    Determinístico (sin LLM): los montos del cliente no salen a un modelo externo.
    """
    data = await calcular_cfo(fecha or date.today())
    if formato == "markdown":
        return PlainTextResponse(content=renderizar_cfo_markdown(data),
                                 media_type="text/markdown; charset=utf-8")
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
