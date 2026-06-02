"""
Agente Riesgo Tributario — inconsistencias, indicadores de fiscalización
y alertas.

Detecta señales que el SII suele observar (crédito de IVA sin registrar,
gastos sin comprobante, deducibilidad anómala, deuda de IVA elevada) y
consolida un score de riesgo y un set de alertas accionables.
"""

from datetime import date, timedelta

from src.agents._common import to_float
from . import _common as c


async def calcular_riesgo(conn, hasta: date, iva: dict, uf: float | None = None) -> dict:
    """Agente Riesgo. Recibe conexión scopeada, el resultado del agente IVA y la UF."""
    uf_valor = uf or c.UF_VALOR
    hace_30  = hasta - timedelta(days=30)
    hace_90  = hasta - timedelta(days=90)

    # Documentos tributarios pendientes de procesar (crédito de IVA sin usar)
    docs = dict(await conn.fetchrow("""
        SELECT COUNT(*) AS cantidad,
               COALESCE(SUM(monto_iva), 0) AS iva_potencial
        FROM documentos_tributarios
        WHERE estado = 'pendiente_revision'
    """) or {})
    n_docs   = int(docs.get("cantidad", 0))
    iva_docs = to_float(docs.get("iva_potencial", 0))

    # Gastos sin comprobante en los últimos 90 días
    gastos_sin_doc = int(await conn.fetchval("""
        SELECT COUNT(*) FROM gastos
        WHERE fecha BETWEEN $1 AND $2
          AND (comprobante IS NULL OR comprobante = '')
    """, hace_90, hasta) or 0)

    # Ratio gasto/ingreso e ingresos afectos (últimos 30 días)
    gastos_30 = to_float(await conn.fetchval(
        "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha BETWEEN $1 AND $2",
        hace_30, hasta) or 0)
    ingresos_30 = to_float(await conn.fetchval("""
        SELECT
            (SELECT COALESCE(SUM(total_hospedaje), 0) FROM reservas
              WHERE fecha_salida BETWEEN $1 AND $2 AND estado = 'checkout')
          + (SELECT COALESCE(SUM(total), 0) FROM consumos_frigobar WHERE fecha BETWEEN $1 AND $2)
          + (SELECT COALESCE(SUM(total), 0) FROM consumos_servicios WHERE fecha BETWEEN $1 AND $2)
    """, hace_30, hasta) or 0)
    ratio_gasto_ingreso = (gastos_30 / ingresos_30 * 100) if ingresos_30 > 0 else 0

    saldo_iva    = to_float(iva.get("acumulado_mes", {}).get("saldo_iva", 0))
    saldo_iva_uf = to_float(iva.get("acumulado_mes", {}).get("saldo_iva_uf", 0))

    inconsistencias: list[dict] = []
    alertas:         list[dict] = []

    # ── Inconsistencias ───────────────────────────────────────────────
    if n_docs > 0:
        inconsistencias.append({
            "codigo": "CREDITO_SIN_REGISTRAR",
            "nivel": "alerta",
            "titulo": f"{n_docs} documento(s) sin registrar",
            "descripcion": f"Hay crédito de IVA sin usar por ${iva_docs:,.0f}. "
                           "Registrar estos documentos reduce tu IVA a pagar.",
        })

    if gastos_sin_doc > 0:
        inconsistencias.append({
            "codigo": "GASTO_SIN_COMPROBANTE",
            "nivel": "alerta",
            "titulo": f"{gastos_sin_doc} gasto(s) sin comprobante (90d)",
            "descripcion": "Gastos sin comprobante no dan derecho a crédito de IVA "
                           "y son observables en una fiscalización.",
        })

    if ratio_gasto_ingreso > c.RATIO_GASTO_INGRESO_ALTO:
        inconsistencias.append({
            "codigo": "DEDUCIBILIDAD_ALTA",
            "nivel": "info",
            "titulo": "Relación gasto/ingreso elevada",
            "descripcion": f"Tus gastos son el {ratio_gasto_ingreso:.1f}% de los ingresos (30d). "
                           "Verifica que todos estén correctamente documentados.",
        })

    # ── Alertas (control + fiscalización) ─────────────────────────────
    if saldo_iva > (c.ALERTA_IVA_DEUDA_UF * uf_valor):
        alertas.append({
            "nivel": "critico",
            "codigo": "IVA_DEUDA_ALTA",
            "titulo": "Deuda de IVA elevada",
            "descripcion": f"Tu saldo de IVA del mes es ${saldo_iva:,.0f} ({saldo_iva_uf:.1f} UF).",
            "recomendacion": "Asegura liquidez antes del vencimiento del F29.",
        })

    if gastos_sin_doc > 0:
        alertas.append({
            "nivel": "alerta",
            "codigo": "DOCUMENTACION_INCOMPLETA",
            "titulo": "Documentación de gastos incompleta",
            "descripcion": f"{gastos_sin_doc} gasto(s) sin comprobante en los últimos 90 días.",
            "recomendacion": "Solicita y registra los comprobantes para respaldar el crédito.",
        })

    dias_f29 = to_float(iva.get("f29", {}).get("dias_para_vencimiento", 99))
    if 0 < dias_f29 <= 5:
        alertas.append({
            "nivel": "info",
            "codigo": "VENCIMIENTO_F29_PROXIMO",
            "titulo": "Vencimiento F29 próximo",
            "descripcion": f"El F29 vence en {int(dias_f29)} día(s).",
            "recomendacion": "Prepara la declaración mensual.",
        })

    # ── Score de riesgo de fiscalización ──────────────────────────────
    if any(a["nivel"] == "critico" for a in alertas):
        score = "alto"
    elif alertas or inconsistencias:
        score = "medio"
    else:
        score = "bajo"

    return {
        "score_riesgo":    score,
        "inconsistencias": inconsistencias,
        "alertas":         alertas,
        "documentos_pendientes": {
            "cantidad":                  n_docs,
            "iva_potencial_recuperable": iva_docs,
        },
        "metricas": {
            "ratio_gasto_ingreso_30d": round(ratio_gasto_ingreso, 1),
            "gastos_sin_comprobante_90d": gastos_sin_doc,
        },
    }
