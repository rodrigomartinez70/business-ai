"""
Agente Cumplimiento — calendario tributario chileno, declaraciones juradas
y próximos vencimientos.

No depende de la base de datos: es conocimiento del calendario del SII.
Calcula qué obligaciones vencen en los próximos `horizonte_dias` y entrega
el calendario anual de referencia.
"""

from datetime import date, timedelta

# Obligaciones mensuales: (día_vencimiento, código, nombre, tipo, descripción)
_MENSUALES = [
    (13, "COTIZ", "Cotizaciones previsionales",   "pago",
     "AFP, salud y seguro de cesantía del personal."),
    (20, "F29",   "Declaración F29 (IVA + PPM)",  "declaracion",
     "IVA débito/crédito y pagos provisionales mensuales del período anterior."),
]

# Obligaciones anuales: ((mes, día), código, nombre, tipo, descripción)
_ANUALES = [
    ((3, 28), "DJ1879", "DJ 1879 — Honorarios",        "declaracion_jurada",
     "Retenciones por rentas de honorarios pagadas en el año."),
    ((3, 28), "DJ1887", "DJ 1887 — Rentas del trabajo", "declaracion_jurada",
     "Sueldos y remuneraciones pagadas al personal."),
    ((4, 30), "F22",    "Declaración de Renta (F22)",   "declaracion",
     "Impuesto a la renta anual del ejercicio comercial."),
    ((6, 30), "DJ1948", "DJ 1948 — Retiros y dividendos", "declaracion_jurada",
     "Retiros, remesas y dividendos distribuidos por la empresa."),
]

# Calendario anual de referencia (siempre presente, para contexto)
_CALENDARIO_ANUAL_REF = [
    {"codigo": "F29",    "nombre": "Declaración F29 (IVA + PPM)",  "periodicidad": "mensual",
     "cuando": "Día 20 del mes siguiente."},
    {"codigo": "COTIZ",  "nombre": "Cotizaciones previsionales",   "periodicidad": "mensual",
     "cuando": "Día 13 del mes siguiente."},
    {"codigo": "DJ1879", "nombre": "DJ 1879 — Honorarios",         "periodicidad": "anual",
     "cuando": "Marzo."},
    {"codigo": "DJ1887", "nombre": "DJ 1887 — Rentas del trabajo", "periodicidad": "anual",
     "cuando": "Marzo."},
    {"codigo": "F22",    "nombre": "Declaración de Renta (F22)",   "periodicidad": "anual",
     "cuando": "Abril."},
    {"codigo": "DJ1948", "nombre": "DJ 1948 — Retiros y dividendos", "periodicidad": "anual",
     "cuando": "Junio."},
]


def _item(fv: date, hoy: date, codigo, nombre, tipo, desc, periodicidad) -> dict:
    return {
        "codigo":         codigo,
        "nombre":         nombre,
        "tipo":           tipo,
        "periodicidad":   periodicidad,
        "fecha":          str(fv),
        "dias_restantes": (fv - hoy).days,
        "descripcion":    desc,
    }


def calcular_cumplimiento(hasta: date, horizonte_dias: int = 60) -> dict:
    """Próximos vencimientos tributarios dentro del horizonte + calendario anual."""
    fin   = hasta + timedelta(days=horizonte_dias)
    items: list[dict] = []

    # Mensuales: recorrer los meses que toca el horizonte
    y, m = hasta.year, hasta.month
    for _ in range((horizonte_dias // 28) + 2):
        for day, cod, nombre, tipo, desc in _MENSUALES:
            try:
                fv = date(y, m, day)
            except ValueError:
                continue
            if hasta <= fv <= fin:
                items.append(_item(fv, hasta, cod, nombre, tipo, desc, "mensual"))
        m += 1
        if m > 12:
            m, y = 1, y + 1

    # Anuales: probar el año en curso y el siguiente
    for (mon, day), cod, nombre, tipo, desc in _ANUALES:
        for yy in (hasta.year, hasta.year + 1):
            fv = date(yy, mon, day)
            if hasta <= fv <= fin:
                items.append(_item(fv, hasta, cod, nombre, tipo, desc, "anual"))

    items.sort(key=lambda x: x["fecha"])

    return {
        "horizonte_dias":        horizonte_dias,
        "proximos_vencimientos": items,
        "calendario_anual":      _CALENDARIO_ANUAL_REF,
    }
