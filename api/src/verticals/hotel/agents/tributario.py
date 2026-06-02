"""
Agente Tributario para PyMEs en Chile.

Coprotor financiero y tributario que proporciona:
1. Predicción de IVA semanal (proyección en tiempo real)
2. Recomendaciones de optimización tributaria
3. Control tributario permanente (alertas, cumplimiento, riesgos)

Sin LLM — SQL puro + lógica de negocio tributaria chilena.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from .... import config
from ....agents._common import fmt_moneda, to_float, var_txt

logger = logging.getLogger(__name__)

# Configuración tributaria Chile
IVA_TASA = 0.19  # Tasa IVA estándar
UF_VALOR = 36_400  # UF aproximado (se actualiza mensualmente)

# Umbrales para alertas
ALERTA_IVA_DEUDA_UF = 50  # Alerta si deuda > 50 UF
ALERTA_INGRESOS_AFECTOS_BAJO = 0.70  # Alerta si < 70% ingresos son afectos a IVA


async def calcular_tributario_semanal(hasta: date) -> dict:
    """
    Análisis tributario semanal para PyMEs en Chile.

    Niveles cubiertos:
    1. Predicción IVA semanal
    2. Recomendaciones de optimización
    3. Control tributario permanente (alertas)
    """
    desde = hasta - timedelta(days=6)  # Última semana completa
    hace_30 = hasta - timedelta(days=30)
    hace_90 = hasta - timedelta(days=90)

    async with config.db_pool.acquire() as conn:

        # ─── NIVEL 1: PREDICCIÓN DE IVA ──────────────────────────────────

        # Ingresos afectos a IVA (hospedaje es afecto)
        ingresos_semana = dict(await conn.fetchrow("""
            SELECT
                COALESCE(SUM(r.total_hospedaje), 0) AS afectos,
                COALESCE(SUM(f.total), 0) AS frigobar_afectos,
                COALESCE(SUM(s.total), 0) AS servicios_afectos
            FROM reservas r
            LEFT JOIN consumos_frigobar f ON f.reserva_id = r.id AND f.fecha BETWEEN $1 AND $2
            LEFT JOIN consumos_servicios s ON s.reserva_id = r.id AND s.fecha BETWEEN $1 AND $2
            WHERE r.fecha_salida BETWEEN $1 AND $2
              AND r.estado = 'checkout'
        """, desde, hasta))

        # Gastos con derecho a crédito de IVA (compras, servicios, etc)
        gastos_semana = dict(await conn.fetchrow("""
            SELECT
                COALESCE(SUM(monto), 0) AS total_gastos,
                COUNT(*) AS n_gastos
            FROM gastos
            WHERE fecha BETWEEN $1 AND $2
        """, desde, hasta))

        # IVA acumulado del mes actual (desde día 1 hasta hoy)
        inicio_mes = date(hasta.year, hasta.month, 1)
        iva_mes = dict(await conn.fetchrow("""
            WITH ingresos_mes AS (
                SELECT COALESCE(SUM(r.total_hospedaje) + COALESCE(SUM(f.total), 0) + COALESCE(SUM(s.total), 0), 0) AS total
                FROM reservas r
                LEFT JOIN consumos_frigobar f ON f.reserva_id = r.id
                LEFT JOIN consumos_servicios s ON s.reserva_id = r.id
                WHERE r.fecha_salida BETWEEN $1 AND $2 AND r.estado = 'checkout'
            ),
            gastos_mes AS (
                SELECT COALESCE(SUM(monto), 0) AS total FROM gastos WHERE fecha BETWEEN $1 AND $2
            )
            SELECT
                ROUND((SELECT total FROM ingresos_mes) * 0.19, 2) AS iva_debito,
                ROUND((SELECT total FROM gastos_mes) * 0.19, 2) AS iva_credito
        """, inicio_mes, hasta))

        # Proyección IVA próximos 7 días (basada en promedio semanal)
        promedio_semanal_ingreso = to_float(ingresos_semana.get("afectos", 0)) + \
                                   to_float(ingresos_semana.get("frigobar_afectos", 0)) + \
                                   to_float(ingresos_semana.get("servicios_afectos", 0))
        promedio_semanal_gasto = to_float(gastos_semana.get("total_gastos", 0))

        iva_debito_proximo = round(promedio_semanal_ingreso * IVA_TASA, 2)
        iva_credito_proximo = round(promedio_semanal_gasto * IVA_TASA, 2)

        # ─── NIVEL 2: RECOMENDACIONES DE OPTIMIZACIÓN ────────────────────

        # % de ingresos que son afectos a IVA
        total_ingresos_semana = promedio_semanal_ingreso
        pct_afectos = (promedio_semanal_ingreso / total_ingresos_semana * 100) if total_ingresos_semana > 0 else 0

        # Análisis de gastos deducibles
        gastos_ultimos_30 = to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha BETWEEN $1 AND $2",
            hace_30, hasta
        ) or 0)

        ingresos_ultimos_30 = to_float(await conn.fetchval("""
            SELECT COALESCE(
                SUM(r.total_hospedaje) + COALESCE(SUM(f.total), 0) + COALESCE(SUM(s.total), 0), 0
            )
            FROM reservas r
            LEFT JOIN consumos_frigobar f ON f.reserva_id = r.id
            LEFT JOIN consumos_servicios s ON s.reserva_id = r.id
            WHERE r.fecha_salida BETWEEN $1 AND $2 AND r.estado = 'checkout'
        """, hace_30, hasta) or 0)

        ratio_gasto_ingreso = (gastos_ultimos_30 / ingresos_ultimos_30 * 100) if ingresos_ultimos_30 > 0 else 0

        # Documentos pendientes de procesar
        docs_pendientes_row = await conn.fetchrow("""
            SELECT
                COUNT(*) AS cantidad,
                COALESCE(SUM(monto_iva), 0) AS iva_potencial,
                COALESCE(SUM(monto_total), 0) AS monto_total
            FROM documentos_tributarios
            WHERE estado = 'pendiente_revision'
        """)
        docs_pendientes = dict(docs_pendientes_row) if docs_pendientes_row else {}
        logger.info(f"✅ Documentos tributarios detectados: cantidad={docs_pendientes.get('cantidad')}, iva=${docs_pendientes.get('iva_potencial'):,.2f}")

        iva_potencial = to_float(docs_pendientes.get("iva_potencial", 0))
        n_docs_pendientes = int(docs_pendientes.get("cantidad", 0))

        # Recomendaciones
        recomendaciones = []

        if n_docs_pendientes > 0:
            recomendaciones.append({
                "tipo": "alerta",
                "prioridad": "alta",
                "titulo": f"⚠️ {n_docs_pendientes} documentos pendientes",
                "descripcion": f"Tienes {n_docs_pendientes} documentos sin procesar. Procesarlos recuperaría ${iva_potencial:,.0f} en crédito de IVA.",
                "impacto": f"Recuperar ${iva_potencial:,.0f} en IVA crédito"
            })

        if pct_afectos < 85:
            recomendaciones.append({
                "tipo": "optimizacion",
                "prioridad": "media",
                "titulo": "Maximizar ingresos afectos a IVA",
                "descripcion": f"Solo el {pct_afectos:.1f}% de ingresos son afectos. Revisa si hay servicios que deberían estar gravados.",
                "impacto": "Aumentar recaudación de IVA accionable"
            })

        if ratio_gasto_ingreso > 40:
            recomendaciones.append({
                "tipo": "optimizacion",
                "prioridad": "media",
                "titulo": "Revisar gastos deducibles",
                "descripcion": f"Tus gastos son el {ratio_gasto_ingreso:.1f}% de ingresos. Verifica que todos estén documentados para crédito de IVA.",
                "impacto": "Maximizar crédito tributario"
            })

        # ─── NIVEL 3: CONTROL TRIBUTARIO PERMANENTE ──────────────────────

        iva_debito_acum = to_float(iva_mes.get("iva_debito", 0))
        iva_credito_acum = to_float(iva_mes.get("iva_credito", 0))
        saldo_iva = iva_debito_acum - iva_credito_acum
        saldo_iva_uf = saldo_iva / UF_VALOR if UF_VALOR > 0 else 0

        alertas = []

        # Alerta 1: Deuda IVA muy alta
        if saldo_iva > (ALERTA_IVA_DEUDA_UF * UF_VALOR):
            alertas.append({
                "nivel": "critico",
                "codigo": "IVA_DEUDA_ALTA",
                "titulo": "Deuda de IVA elevada",
                "descripcion": f"Tu deuda acumulada es ${saldo_iva:,.0f} ({saldo_iva_uf:.1f} UF). Vencimiento F29 típicamente entre días 20-25.",
                "recomendacion": "Asegurate de tener liquidez suficiente para pago"
            })

        # Alerta 2: Baja cobertura de gastos deducibles
        if pct_afectos > 80 and ratio_gasto_ingreso < 20:
            alertas.append({
                "nivel": "alerta",
                "codigo": "BAJA_DEDUCIBILIDAD",
                "titulo": "Baja deducibilidad de gastos",
                "descripcion": "Tus gastos documentados son bajos respecto a ingresos. Revisa documentación y comprobantes.",
                "recomendacion": "Auditar documentación de gastos para crédito de IVA"
            })

        # Alerta 3: Período F29 próximo
        dias_para_vencimiento = _dias_para_vencimiento_f29(hasta)
        if dias_para_vencimiento <= 5 and dias_para_vencimiento > 0:
            alertas.append({
                "nivel": "info",
                "codigo": "VENCIMIENTO_F29_PROXIMO",
                "titulo": "Vencimiento F29 próximo",
                "descripcion": f"Vencimiento estimado en {dias_para_vencimiento} días",
                "recomendacion": "Preparar información para declaración mensual"
            })

        # ─── IMPUESTOS Y RETENCIONES ESPECÍFICAS ─────────────────────────

        # Retención en la fuente (si aplica a servicios)
        servicios_uf = Decimal(str(to_float(await conn.fetchval(
            "SELECT COALESCE(SUM(total), 0) FROM consumos_servicios WHERE fecha BETWEEN $1 AND $2",
            inicio_mes, hasta
        ) or 0)))

        # En Chile, servicios sobre cierto monto pueden tener retención impuesto único
        retencion_servicios = round(float(servicios_uf) * 0.04, 2) if servicios_uf > 0 else 0  # 4% es aproximado

    # ─────────────────────────────────────────────────────────────────────
    # CONSTRUCCIÓN DE RESPUESTA
    # ─────────────────────────────────────────────────────────────────────

    return {
        "periodo": {
            "semana": {"inicio": str(desde), "fin": str(hasta)},
            "mes": {"inicio": str(inicio_mes), "fin": str(hasta)},
        },
        "nivel_1_prediccion": {
            "semana_actual": {
                "ingresos_afectos": to_float(ingresos_semana.get("afectos", 0)),
                "iva_debito": round(to_float(ingresos_semana.get("afectos", 0)) * IVA_TASA, 2),
                "gastos": to_float(gastos_semana.get("total_gastos", 0)),
                "iva_credito": round(to_float(gastos_semana.get("total_gastos", 0)) * IVA_TASA, 2),
                "n_gastos": int(gastos_semana.get("n_gastos", 0)),
            },
            "proximos_7_dias": {
                "iva_debito_estimado": iva_debito_proximo,
                "iva_credito_estimado": iva_credito_proximo,
            },
            "acumulado_mes": {
                "iva_debito_acum": iva_debito_acum,
                "iva_credito_acum": iva_credito_acum,
                "saldo_iva": saldo_iva,
                "saldo_iva_uf": round(saldo_iva_uf, 2),
                "estado": "deuda" if saldo_iva > 0 else "saldo_a_favor",
            },
        },
        "nivel_2_optimizacion": {
            "pct_ingresos_afectos": round(pct_afectos, 1),
            "ratio_gasto_ingreso_30d": round(ratio_gasto_ingreso, 1),
            "documentos_pendientes": {
                "cantidad": n_docs_pendientes,
                "iva_potencial_recuperable": iva_potencial,
            },
            "recomendaciones": recomendaciones,
        },
        "nivel_3_control": {
            "alertas": alertas,
            "dias_para_vencimiento_f29": dias_para_vencimiento,
            "proximo_vencimiento_aprox": _fecha_vencimiento_f29(hasta),
            "retenciones_pendientes": {
                "servicios": retencion_servicios,
            },
        },
    }


def _dias_para_vencimiento_f29(fecha: date) -> int:
    """Calcula días para vencimiento de F29 desde la fecha dada."""
    # En Chile, F29 vence entre días 20-25 del mes siguiente (usamos 22)
    if fecha.month == 12:
        vencimiento = date(fecha.year + 1, 1, 22)
    else:
        vencimiento = date(fecha.year, fecha.month + 1, 22)

    dias = (vencimiento - fecha).days
    return max(0, dias)


def _fecha_vencimiento_f29(fecha: date) -> str:
    """Retorna fecha estimada de vencimiento F29."""
    if fecha.month == 12:
        vencimiento = date(fecha.year + 1, 1, 22)
    else:
        vencimiento = date(fecha.year, fecha.month + 1, 22)
    return str(vencimiento)
