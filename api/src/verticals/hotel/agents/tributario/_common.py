"""
Constantes y helpers tributarios chilenos compartidos por los agentes
del Copiloto Tributario (IVA, Cumplimiento, Riesgo).
"""

from datetime import date

# Tasa IVA estándar en Chile
IVA_TASA = 0.19

# UF de respaldo si la API del Banco Central no responde.
# El valor real diario lo obtiene economia.obtener_uf() y se pasa a los agentes.
UF_VALOR = 36_400

# Umbrales de alerta / riesgo
ALERTA_IVA_DEUDA_UF      = 50    # deuda de IVA elevada por encima de N UF
PCT_AFECTOS_BAJO         = 85    # % ingresos afectos por debajo del cual se alerta
RATIO_GASTO_INGRESO_ALTO = 40    # gasto/ingreso (%) por encima del cual se revisa

# Otros componentes del F29 (además del IVA)
PPM_TASA             = 0.0025    # Pago Provisional Mensual: % sobre ingresos brutos (configurable)
RETENCION_HONORARIOS = 0.1375   # retención boletas de honorarios de terceros (2025)

# Categorías de gasto que NO generan crédito de IVA (remuneraciones y honorarios).
NO_AFECTO_IVA = ("Personal", "Honorarios")


def fecha_vencimiento_f29(periodo: date) -> date:
    """
    Fecha de vencimiento del F29 (IVA mensual) correspondiente al período `periodo`.
    En Chile vence el día 20 del mes siguiente para declaración/pago por internet.
    """
    if periodo.month == 12:
        return date(periodo.year + 1, 1, 20)
    return date(periodo.year, periodo.month + 1, 20)


def dias_para_vencimiento_f29(hoy: date) -> int:
    """Días desde `hoy` hasta el vencimiento del F29 del mes en curso."""
    return max(0, (fecha_vencimiento_f29(hoy) - hoy).days)
