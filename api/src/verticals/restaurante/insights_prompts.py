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
    "pnl_mensual": """
Analizá el P&L mensual de un restaurante:
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
    a   = data.get("actual", {})
    c   = data.get("comparativas", {})
    met = data.get("metricas", {})
    var_ing = c.get("ingresos", {}).get("vs_mes_anterior")
    var_res = c.get("resultado", {}).get("vs_mes_anterior")
    ing_txt = f"{var_ing:+.1f}%" if var_ing is not None else "sin dato"
    res_txt = f"{var_res:+.1f}%" if var_res is not None else "sin dato"
    return (
        f"Mes: {data.get('mes_nombre', '')} ({'parcial' if data.get('parcial') else 'completo'})\n"
        f"Resultado: {a.get('resultado', 0):,.0f} (margen {a.get('margen_pct', 0):.1f}%)\n"
        f"Ingresos vs mes anterior: {ing_txt}\n"
        f"Resultado vs mes anterior: {res_txt}\n"
        f"Food cost: {met.get('food_cost_pct', 0):.1f}%\n"
        f"Ticket promedio: {met.get('ticket_promedio', 0):,.0f}"
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
    return (
        f"Ventas del día/semana: {'sí' if t.get('ventas', 0) else 'sin ventas'}\n"
        f"Cobrado vs ventas: {'completo' if t.get('cobrado', 0) >= t.get('ventas', 0) else 'pendiente'}\n"
        f"Resultado: {t.get('resultado', 0):,.0f}\n"
        f"Ticket promedio: {t.get('ticket_promedio', 0):,.0f}"
    )


RESUMIDORES: dict[str, object] = {
    "ventas":         resumir_ventas,
    "pnl_mensual":    resumir_pnl,
    "control_gastos": resumir_control_gastos,
    "cierre_diario":  resumir_cierre,
}
