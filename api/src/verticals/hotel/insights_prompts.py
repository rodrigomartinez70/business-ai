"""
Prompts e insights específicos del vertical hotelero.
Importados por src/agents/insights.py según el BUSINESS_VERTICAL activo.
"""

SYSTEM = (
    "Eres un consultor de gestión hotelera. Tu rol es convertir datos operativos "
    "en recomendaciones concretas para el dueño. Nunca repitas los números del contexto — "
    "usá términos relativos ('por encima del promedio', 'tendencia negativa', etc.). "
    "Respondé SOLO con una lista de bullets en español, sin introducción ni cierre."
)

PROMPTS: dict[str, str] = {
    "cierre_diario": """
Analizá el resumen del día de hoy de un hotel:
{resumen}

Generá exactamente 3 insights accionables para el dueño:
- Uno sobre la operación del día (ocupación, movimientos)
- Uno sobre la caja y cobros pendientes
- Uno sobre el resultado y qué palanca tiene para mejorar mañana
""",
    "control_gastos": """
Analizá el reporte de control de gastos semanal de un hotel:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre la categoría de gasto más preocupante
- Uno sobre proveedores o gastos sin clasificar si los hay
- Uno sobre una acción concreta para reducir o controlar costos
""",
    "pnl": """
Analizá el P&L comparativo YTD de un hotel:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre el desempeño vs períodos anteriores
- Uno sobre la estructura de ingresos o gastos que más impacta el margen
- Uno sobre una acción estratégica para mejorar el GOP el próximo mes
""",
    "revenue_management": """
Analizá el reporte de revenue management de un hotel:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre la estrategia de precios para los próximos días
- Uno sobre el canal de venta más conveniente o a potenciar
- Uno sobre una oportunidad concreta de ingreso adicional
""",
    "cash_flow": """
Analizá la proyección de cash flow de un hotel para las próximas semanas:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre el riesgo de liquidez identificado (si existe)
- Uno sobre cómo adelantar cobros o diferir gastos para mejorar el flujo
- Uno sobre una acción preventiva si el flujo proyectado es insuficiente
""",
    "rentabilidad_canal": """
Analizá el ranking de rentabilidad por canal de venta de un hotel:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre el canal más rentable y cómo potenciarlo
- Uno sobre el canal con mayor tasa de cancelación y cómo reducirla
- Uno sobre el mix de canales óptimo para el próximo mes
""",
    "alertas": """
Analizá los KPIs operativos de un hotel con sus alertas activas:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre la causa probable de las alertas activas
- Uno sobre la acción más urgente que debe tomar el dueño hoy
- Uno sobre cómo prevenir que estas alertas se repitan la semana próxima
""",
}


def resumir_cierre(data: dict) -> str:
    r   = data["resumen"]
    ocu = data["ocupacion"]
    cob = data["cobros"]
    gas = data["gastos"]
    return (
        f"Ocupación: {ocu['pct_ocupacion']}% ({ocu['en_casa']}/{ocu['total_habitaciones']} hab)\n"
        f"Check-ins hoy: {data['movimientos']['checkins']}, Check-outs: {data['movimientos']['checkouts']}\n"
        f"Estado GOP: {r['gop_estado']} (devengado vs caja)\n"
        f"Cobros pendientes: {'hay' if cob['pendiente'] > 0 else 'ninguno'}\n"
        f"Gastos del día: {'registrados' if gas['total'] > 0 else 'sin gastos registrados'}\n"
        f"Comisiones OTA del día: {'hay' if data['comisiones_ota'] else 'ninguna'}"
    )


def resumir_control_gastos(data: dict) -> str:
    r   = data["resumen"]
    var = r.get("variacion_pct")
    var_txt = f"{var:+.1f}%" if var is not None else "sin referencia"
    alertas = data.get("alertas", [])
    sin_cat = data.get("sin_categoria", {})
    top_cat = data["categorias"][:3] if data.get("categorias") else []
    return (
        f"Variación total de gastos vs período anterior: {var_txt}\n"
        f"Categorías en alerta ({[a['nivel'] for a in alertas]}): "
        f"{', '.join(a['categoria'] for a in alertas) or 'ninguna'}\n"
        f"Top categorías por monto: {', '.join(c['categoria'] for c in top_cat)}\n"
        f"Gastos sin categoría: {sin_cat.get('n', 0)} registros\n"
        f"Proveedores nuevos: {len(data.get('proveedores_nuevos', []))}"
    )


def resumir_pnl(data: dict) -> str:
    r = data.get("resumen", {})
    vi = r.get("var_ingresos_pct")
    vr = r.get("var_resultado_pct")
    vi_txt = f"{vi:+.1f}%" if vi is not None else "sin dato"
    vr_txt = f"{vr:+.1f}%" if vr is not None else "sin dato"
    estado = "positivo" if r.get("resultado_neto", 0) >= 0 else "negativo"
    return (
        "P&L comparativo YTD (año actual vs año anterior):\n"
        f"Resultado neto: {estado}\n"
        f"Margen bruto: {r.get('margen_bruto_pct', 0):.1f}%\n"
        f"Ingresos netos vs año anterior: {vi_txt}\n"
        f"Resultado neto vs año anterior: {vr_txt}"
    )


def resumir_revenue(data: dict) -> str:
    s   = data["snapshot"]
    h30 = data["historico"]["30d"]
    oport = data["oportunidades_precio"]
    canales = sorted(data["canales"], key=lambda c: c["ingresos_netos"], reverse=True)
    return (
        f"Ocupación hoy: {s['ocupacion_pct']:.1f}% vs promedio 30d: {h30['ocupacion_pct']:.1f}%\n"
        f"ADR hoy vs promedio 30d: {'por encima' if s['adr'] > h30['adr'] else 'por debajo'}\n"
        f"Oportunidades de precio próximos días: {len(oport)} "
        f"({'días con alta ocupación y tarifa baja' if oport else 'ninguna detectada'})\n"
        f"Canal más rentable (30d): {canales[0]['canal'] if canales else '—'}\n"
        f"Proyección 7d: ocupación promedio {data['proyeccion']['ocupacion_prom_7d']:.1f}%"
    )


def resumir_cash_flow(data: dict) -> str:
    r   = data["resumen"]
    sem = data["semaforo"]
    cob = r["cobros_pendientes"]
    cob_txt = f"{r['semanas_cobertura']:.1f} semanas" if r['semanas_cobertura'] is not None else "sin datos"
    flujo_txt = "positivo" if r['flujo_neto_proyectado'] >= 0 else "negativo"
    pend_txt = "hay" if cob > 0 else "ninguno"
    ing_txt = "hay reservas confirmadas" if r['ingresos_proyectados'] > 0 else "sin reservas confirmadas"
    return (
        f"Semáforo de liquidez: {sem.upper()}\n"
        f"Cobertura mínima proyectada: {cob_txt}\n"
        f"Flujo neto proyectado 8 semanas: {flujo_txt}\n"
        f"Cobros pendientes: {pend_txt}\n"
        f"Ingresos proyectados: {ing_txt}"
    )


def resumir_rentabilidad_canal(data: dict) -> str:
    t   = data["totales"]
    ins = data["insights"]
    canales = data["canales"]
    cancel_alto = [c for c in canales if c["tasa_cancel_pct"] > 15]
    return (
        f"Canal más rentable: {ins['canal_mas_rentable'] or '—'}\n"
        f"Canal más confiable: {ins['canal_mas_confiable'] or '—'}\n"
        f"Tasa de cancelación global: {t['tasa_cancel_pct']:.1f}%\n"
        f"Canales con cancelación >15%: {', '.join(c['canal'] for c in cancel_alto) or 'ninguno'}\n"
        f"Mix: {len([c for c in canales if c['ingresos_netos'] > 0])} canales activos"
    )


def resumir_alertas(data: dict) -> str:
    alertas = data.get("alertas", [])
    kpis    = data.get("kpis", [])
    criticos = [a for a in alertas if a["nivel"] == "critico"]
    return (
        f"Estado general: {data.get('estado_general', 'ok').upper()}\n"
        f"Alertas activas: {len(alertas)} ({len(criticos)} críticas)\n"
        f"KPIs en alerta: {', '.join(a['kpi'] for a in alertas) or 'ninguno'}\n"
        f"KPIs OK: {', '.join(k['name'] for k in kpis if k.get('valor') is not None and k['name'] not in [a['kpi'] for a in alertas])}"
    )


RESUMIDORES: dict[str, object] = {
    "cierre_diario":      resumir_cierre,
    "control_gastos":     resumir_control_gastos,
    "pnl":        resumir_pnl,
    "revenue_management": resumir_revenue,
    "cash_flow":          resumir_cash_flow,
    "rentabilidad_canal": resumir_rentabilidad_canal,
    "alertas":            resumir_alertas,
}
