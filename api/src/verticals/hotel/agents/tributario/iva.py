"""
Agente IVA — débito, crédito, saldo, proyección y F29.

Calcula el IVA débito (sobre ingresos afectos), el IVA crédito (sobre gastos
con derecho a crédito), el saldo del mes en curso, una proyección a 7 días y
el estado del F29 (vencimiento y monto estimado a pagar).
"""

from datetime import date, timedelta

from src.agents._common import to_float
from . import _common as c


async def calcular_iva(conn, hasta: date, uf: float | None = None) -> dict:
    """Agente IVA. Recibe una conexión ya scopeada al tenant y la UF del día."""
    uf_valor   = uf or c.UF_VALOR
    desde      = hasta - timedelta(days=6)
    inicio_mes = date(hasta.year, hasta.month, 1)

    # Ingresos afectos de la última semana (hospedaje + frigobar + servicios).
    # Agregados separados para evitar el fan-out del JOIN uno-a-muchos.
    ingresos_semana = dict(await conn.fetchrow("""
        SELECT
            (SELECT COALESCE(SUM(total_hospedaje), 0) FROM reservas
              WHERE fecha_salida BETWEEN $1 AND $2 AND estado = 'checkout') AS afectos,
            (SELECT COALESCE(SUM(total), 0) FROM consumos_frigobar
              WHERE fecha BETWEEN $1 AND $2)  AS frigobar_afectos,
            (SELECT COALESCE(SUM(total), 0) FROM consumos_servicios
              WHERE fecha BETWEEN $1 AND $2)  AS servicios_afectos
    """, desde, hasta))

    # Gastos de la semana (proxy de crédito de IVA)
    gastos_semana = dict(await conn.fetchrow("""
        SELECT COALESCE(SUM(monto), 0) AS total_gastos, COUNT(*) AS n_gastos
        FROM gastos WHERE fecha BETWEEN $1 AND $2
    """, desde, hasta))

    # IVA acumulado del mes en curso (día 1 → hasta). Agregados separados
    # (sin fan-out): hospedaje devengado por checkout + consumos por su fecha.
    iva_mes = dict(await conn.fetchrow("""
        WITH ingresos_mes AS (
            SELECT
                (SELECT COALESCE(SUM(total_hospedaje), 0) FROM reservas
                  WHERE fecha_salida BETWEEN $1 AND $2 AND estado = 'checkout')
              + (SELECT COALESCE(SUM(total), 0) FROM consumos_frigobar
                  WHERE fecha BETWEEN $1 AND $2)
              + (SELECT COALESCE(SUM(total), 0) FROM consumos_servicios
                  WHERE fecha BETWEEN $1 AND $2) AS total
        ),
        gastos_mes AS (
            SELECT COALESCE(SUM(monto), 0) AS total FROM gastos WHERE fecha BETWEEN $1 AND $2
        )
        SELECT
            ROUND((SELECT total FROM ingresos_mes) * 0.19, 2) AS iva_debito,
            ROUND((SELECT total FROM gastos_mes)   * 0.19, 2) AS iva_credito
    """, inicio_mes, hasta))

    # Crédito real desde facturas registradas (F29 exacto); si no hay
    # documentos registrados, se cae a la estimación gastos × 19%.
    docs_credito = dict(await conn.fetchrow("""
        SELECT COUNT(*) AS n, COALESCE(SUM(monto_iva), 0) AS iva
        FROM documentos_tributarios
        WHERE estado = 'registrado' AND fecha BETWEEN $1 AND $2
    """, inicio_mes, hasta))

    ingreso_semana = (to_float(ingresos_semana.get("afectos", 0))
                      + to_float(ingresos_semana.get("frigobar_afectos", 0))
                      + to_float(ingresos_semana.get("servicios_afectos", 0)))
    gasto_semana = to_float(gastos_semana.get("total_gastos", 0))

    iva_debito_acum   = to_float(iva_mes.get("iva_debito", 0))
    credito_estimado  = to_float(iva_mes.get("iva_credito", 0))
    n_docs_registrados = int(docs_credito.get("n", 0))
    if n_docs_registrados > 0:
        iva_credito_acum = to_float(docs_credito.get("iva", 0))
        credito_fuente   = "documentos"
    else:
        iva_credito_acum = credito_estimado
        credito_fuente   = "estimado"
    saldo_iva    = iva_debito_acum - iva_credito_acum
    saldo_iva_uf = saldo_iva / uf_valor if uf_valor else 0

    # F29: lo que se pagaría es el saldo positivo (débito > crédito)
    monto_f29 = max(0.0, saldo_iva)

    return {
        "semana_actual": {
            "ingresos_afectos": ingreso_semana,
            "iva_debito":       round(ingreso_semana * c.IVA_TASA, 2),
            "gastos":           gasto_semana,
            "iva_credito":      round(gasto_semana * c.IVA_TASA, 2),
            "n_gastos":         int(gastos_semana.get("n_gastos", 0)),
        },
        "proximos_7_dias": {
            "iva_debito_estimado":  round(ingreso_semana * c.IVA_TASA, 2),
            "iva_credito_estimado": round(gasto_semana * c.IVA_TASA, 2),
        },
        "acumulado_mes": {
            "iva_debito_acum":   iva_debito_acum,
            "iva_credito_acum":  iva_credito_acum,
            "iva_credito_fuente": credito_fuente,
            "saldo_iva":         saldo_iva,
            "saldo_iva_uf":      round(saldo_iva_uf, 2),
            "estado":            "deuda" if saldo_iva > 0 else "saldo_a_favor",
        },
        "f29": {
            "periodo":               inicio_mes.strftime("%Y-%m"),
            "monto_estimado":        round(monto_f29, 2),
            "monto_estimado_uf":     round(monto_f29 / uf_valor, 2) if uf_valor else 0,
            "vencimiento":           str(c.fecha_vencimiento_f29(hasta)),
            "dias_para_vencimiento": c.dias_para_vencimiento_f29(hasta),
        },
        "uf_referencia": round(uf_valor, 2),
    }
