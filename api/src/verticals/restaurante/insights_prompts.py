"""
Prompts e insights específicos del vertical restaurante.
Importados por src/agents/insights.py según el vertical activo.
"""

SYSTEM = (
    "Eres un consultor de gestión gastronómica. Convertís datos operativos de un "
    "restaurante en recomendaciones concretas para el dueño. Nunca repitas los "
    "números del contexto — usá términos relativos ('por encima del promedio', "
    "'tendencia negativa', etc.). Respondé SOLO con una lista de bullets en "
    "español, sin introducción ni cierre."
)

PROMPTS: dict[str, str] = {
    "ventas": """
Analizá el resumen de ventas de un restaurante:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre la tendencia de ventas y el ticket promedio
- Uno sobre el canal (salón/delivery) o producto a potenciar
- Uno sobre una acción concreta para subir la venta o el margen
""",
    "pnl": """
Analizá el P&L comparativo YTD de un restaurante:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre el desempeño vs períodos anteriores
- Uno sobre el food cost / estructura de costos que más impacta el margen
- Uno sobre una acción estratégica para mejorar el resultado el próximo mes
""",
    "control_gastos": """
Analizá el control de gastos semanal de un restaurante:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre la categoría de gasto más preocupante
- Uno sobre proveedores o gastos sin clasificar si los hay
- Uno sobre una acción concreta para controlar costos
""",
    "cierre_diario": """
Analizá el cierre del día de un restaurante:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre la venta y el ticket del día
- Uno sobre la caja y la conciliación de cobros
- Uno sobre una palanca para mejorar mañana
""",
    "marketing": """
Analizá el resumen de marketing digital (Meta Ads) de un negocio:
{resumen}

Generá exactamente 3 insights accionables:
- Uno sobre la eficiencia de la inversión (CPL / conversión) y su tendencia
- Uno sobre qué campaña potenciar o pausar
- Uno sobre una acción concreta para bajar el costo por lead o subir los leads
""",
}


def resumir_ventas(data: dict) -> str:
    r = data.get("resumen", {})
    var = r.get("variacion_pct")
    var_txt = f"{var:+.1f}%" if var is not None else "sin referencia"
    canales = sorted(data.get("por_canal", []), key=lambda c: c.get("ventas", 0), reverse=True)
    top = data.get("top_productos", [])[:3]
    return (
        f"Variación de ventas vs período anterior: {var_txt}\n"
        f"Ticket promedio: {'alto' if r.get('ticket_promedio', 0) else 'sin datos'}\n"
        f"Margen bruto: {r.get('margen_pct', 0):.1f}% (food cost {100 - r.get('margen_pct', 0):.1f}%)\n"
        f"Canal principal: {canales[0]['canal'] if canales else '—'}\n"
        f"Productos top: {', '.join(p.get('producto', '') for p in top) or 'sin datos'}\n"
        f"N° pedidos: {r.get('n_pedidos', 0)}"
    )


def resumir_pnl(data: dict) -> str:
    r = data.get("resumen", {})
    vi = r.get("var_ingresos_pct")
    vr = r.get("var_resultado_pct")
    vi_txt = f"{vi:+.1f}%" if vi is not None else "sin dato"
    vr_txt = f"{vr:+.1f}%" if vr is not None else "sin dato"
    food_cost = 100 - r.get("margen_bruto_pct", 0)
    estado = "positivo" if r.get("resultado_neto", 0) >= 0 else "negativo"
    return (
        "P&L comparativo YTD (año actual vs año anterior):\n"
        f"Resultado neto: {estado}\n"
        f"Margen bruto: {r.get('margen_bruto_pct', 0):.1f}% (food cost {food_cost:.1f}%)\n"
        f"Ingresos netos vs año anterior: {vi_txt}\n"
        f"Resultado neto vs año anterior: {vr_txt}"
    )


def resumir_control_gastos(data: dict) -> str:
    r = data.get("resumen", {})
    var = r.get("variacion_pct")
    var_txt = f"{var:+.1f}%" if var is not None else "sin referencia"
    alertas = data.get("alertas", [])
    top_cat = data.get("categorias", [])[:3]
    return (
        f"Variación total de gastos vs período anterior: {var_txt}\n"
        f"Categorías en alerta: {', '.join(a.get('categoria', '') for a in alertas) or 'ninguna'}\n"
        f"Top categorías: {', '.join(c.get('categoria', '') for c in top_cat)}\n"
        f"Gastos sin categoría: {data.get('sin_categoria', {}).get('n', 0)}"
    )


def resumir_cierre(data: dict) -> str:
    t = data.get("totales", {})
    estado = "positivo" if t.get("resultado", 0) >= 0 else "negativo"
    return (
        f"Ventas del día/semana: {'sí' if t.get('ventas', 0) else 'sin ventas'}\n"
        f"Cobrado vs ventas: {'completo' if t.get('cobrado', 0) >= t.get('ventas', 0) else 'pendiente'}\n"
        f"Resultado: {estado}\n"
        f"Ticket promedio: {'registrado' if t.get('ticket_promedio', 0) else 'sin datos'}"
    )


def resumir_marketing(data: dict) -> str:
    r = data.get("resumen", {})
    vi = r.get("var_inversion_pct"); vl = r.get("var_leads_pct")
    vi_txt = f"{vi:+.1f}%" if vi is not None else "sin referencia"
    vl_txt = f"{vl:+.1f}%" if vl is not None else "sin referencia"
    # Privacidad: solo %, ratios y nombres — sin montos absolutos.
    return (
        "Marketing digital (Meta Ads), período vs anterior:\n"
        f"Inversión vs período anterior: {vi_txt}\n"
        f"Leads vs período anterior: {vl_txt}\n"
        f"Conversión clic→lead: {r.get('conversion_clic_lead', 0):.1f}%\n"
        f"CTR: {r.get('ctr', 0):.2f}%\n"
        f"Campaña más eficiente (mejor CPL): {data.get('mejor_campana') or '—'}\n"
        f"Campaña menos eficiente: {data.get('peor_campana') or '—'}\n"
        f"Alertas activas: {len(data.get('alertas', []))}"
    )


RESUMIDORES: dict[str, object] = {
    "ventas":         resumir_ventas,
    "pnl":    resumir_pnl,
    "control_gastos": resumir_control_gastos,
    "cierre_diario":  resumir_cierre,
    "marketing":      resumir_marketing,
}
