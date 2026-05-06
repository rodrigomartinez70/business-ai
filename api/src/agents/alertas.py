"""
Agente 8 — Indicadores y Alertas Tempranas.

Calcula KPIs financieros directamente desde la DB (sin LLM) y evalúa
umbrales definidos en config.yaml. Diseñado para ser llamado por cron.
"""

from datetime import date, timedelta

from .. import config


# ─────────────────────────────────────────────────────────────
# Cálculo de KPIs
# ─────────────────────────────────────────────────────────────

async def calcular_kpis(periodo_dias: int) -> dict:
    """Ejecuta SQL determinístico para obtener KPIs del período."""
    fecha_fin = date.today()
    fecha_inicio = fecha_fin - timedelta(days=periodo_dias - 1)

    async with config.db_pool.acquire() as conn:
        # Habitaciones activas
        hab_activas = await conn.fetchval(
            "SELECT COUNT(*) FROM habitaciones WHERE activa = TRUE"
        )

        # Ocupación: reservas con checkin activo hoy
        reservas_checkin = await conn.fetchval(
            "SELECT COUNT(*) FROM reservas WHERE estado = 'checkin'"
        )
        ocupacion_pct = round(
            (reservas_checkin / hab_activas * 100) if hab_activas > 0 else 0.0, 1
        )

        # Ingresos de hospedaje y noches del período
        row = await conn.fetchrow(
            """
            SELECT
                COALESCE(SUM(total_hospedaje), 0) AS ingresos_hospedaje,
                COALESCE(SUM(noches), 0)          AS total_noches
            FROM reservas
            WHERE fecha_entrada >= $1
              AND fecha_entrada <= $2
              AND estado IN ('checkin', 'checkout')
            """,
            fecha_inicio, fecha_fin,
        )
        ingresos_hospedaje = float(row["ingresos_hospedaje"])
        total_noches = int(row["total_noches"])

        adr    = round(ingresos_hospedaje / total_noches if total_noches > 0 else 0.0, 2)
        revpar = round(
            ingresos_hospedaje / (hab_activas * periodo_dias) if hab_activas > 0 else 0.0, 2
        )

        # Ingresos totales del período (pagos cobrados)
        ingresos_total = float(await conn.fetchval(
            """
            SELECT COALESCE(SUM(monto), 0)
            FROM pagos
            WHERE fecha >= $1 AND fecha <= $2 AND estado = 'pagado'
            """,
            fecha_inicio, fecha_fin,
        ))

        # Gastos del período
        gastos_total = float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha >= $1 AND fecha <= $2",
            fecha_inicio, fecha_fin,
        ))

        # Pagos pendientes de cobro (acumulado, no solo el período)
        pagos_pendientes = float(await conn.fetchval(
            "SELECT COALESCE(SUM(monto), 0) FROM pagos WHERE estado = 'pendiente'"
        ))

    gop           = round(ingresos_total - gastos_total, 2)
    quema_diaria  = round(gastos_total / periodo_dias, 2) if periodo_dias > 0 else 0.0

    return {
        "fecha_inicio":     str(fecha_inicio),
        "fecha_fin":        str(fecha_fin),
        "periodo_dias":     periodo_dias,
        "hab_activas":      int(hab_activas),
        "reservas_checkin": int(reservas_checkin),
        "ocupacion_pct":    ocupacion_pct,
        "adr":              adr,
        "revpar":           revpar,
        "ingresos_total":   ingresos_total,
        "gastos_total":     gastos_total,
        "gop":              gop,
        "quema_diaria":     quema_diaria,
        "pagos_pendientes": pagos_pendientes,
    }


# ─────────────────────────────────────────────────────────────
# Evaluación de umbrales
# ─────────────────────────────────────────────────────────────

def evaluar_umbrales(kpis: dict, cfg: dict) -> list[dict]:
    """Compara KPIs contra los umbrales de config.yaml → lista de alertas."""
    umbrales = cfg.get("alertas", {}).get("umbrales", {})
    alertas  = []

    def _alerta(kpi: str, valor, umbral_desc: str, nivel: str):
        alertas.append({"kpi": kpi, "valor": valor, "umbral": umbral_desc, "nivel": nivel})

    min_ocup = umbrales.get("ocupacion_minima_pct")
    if min_ocup is not None and kpis["ocupacion_pct"] < min_ocup:
        _alerta("Ocupación", f"{kpis['ocupacion_pct']}%", f"mínimo {min_ocup}%", "alerta")

    gop_min = umbrales.get("gop_minimo")
    if gop_min is not None and kpis["gop"] < gop_min:
        nivel = "critico" if kpis["gop"] < 0 else "alerta"
        _alerta("GOP", kpis["gop"], f"mínimo {gop_min}", nivel)

    pend_max = umbrales.get("pagos_pendientes_max")
    if pend_max is not None and kpis["pagos_pendientes"] > pend_max:
        _alerta("Pagos pendientes", kpis["pagos_pendientes"], f"máximo {pend_max}", "alerta")

    quema_max = umbrales.get("quema_caja_diaria_max")
    if quema_max is not None and kpis["quema_diaria"] > quema_max:
        _alerta("Quema diaria", kpis["quema_diaria"], f"máximo {quema_max}", "alerta")

    return alertas


# ─────────────────────────────────────────────────────────────
# Renderizado del reporte
# ─────────────────────────────────────────────────────────────

def _fmt(valor: float, cfg: dict) -> str:
    """Formatea un valor numérico como moneda según config.yaml."""
    currency  = cfg.get("currency", {})
    symbol    = currency.get("symbol", "$")
    sep_miles = currency.get("thousands_separator", ".")
    sep_dec   = currency.get("decimal_separator", ",")
    decimales = int(currency.get("decimal_places", 0))

    formatted = f"{valor:,.{decimales}f}"
    # Python usa coma para miles y punto para decimal — intercambiar
    formatted = (
        formatted
        .replace(",", "\x00")   # miles → placeholder
        .replace(".", sep_dec)   # punto → sep decimal del negocio
        .replace("\x00", sep_miles)  # placeholder → sep miles del negocio
    )
    return f"{symbol}{formatted}"


def _estado_kpi(kpi_name: str, alertas: list[dict]) -> str:
    match = next((a for a in alertas if a["kpi"] == kpi_name), None)
    if not match:
        return "✅ OK"
    icono = "🚨" if match["nivel"] == "critico" else "⚠️"
    return f"{icono} {match['umbral']}"


def renderizar_reporte(kpis: dict, alertas: list[dict], cfg: dict) -> str:
    biz_name = cfg.get("business", {}).get("name", "Negocio")

    tiene_critico = any(a["nivel"] == "critico" for a in alertas)
    if tiene_critico:
        estado_general, icono_gral = "CRÍTICO", "🚨"
    elif alertas:
        estado_general, icono_gral = "ALERTA", "⚠️"
    else:
        estado_general, icono_gral = "OK", "✅"

    lines = [
        f"## {icono_gral} KPIs — {biz_name}",
        f"**Período:** {kpis['fecha_inicio']} → {kpis['fecha_fin']} ({kpis['periodo_dias']} días)",
        f"**Estado general:** {estado_general}",
        "",
        "| Indicador | Valor | Estado |",
        "|-----------|-------|--------|",
        f"| Ocupación (hoy) | {kpis['ocupacion_pct']}% ({kpis['reservas_checkin']}/{kpis['hab_activas']} hab.) | {_estado_kpi('Ocupación', alertas)} |",
        f"| ADR | {_fmt(kpis['adr'], cfg)} | ✅ OK |",
        f"| RevPAR | {_fmt(kpis['revpar'], cfg)} | ✅ OK |",
        f"| Ingresos período | {_fmt(kpis['ingresos_total'], cfg)} | ✅ OK |",
        f"| Gastos período | {_fmt(kpis['gastos_total'], cfg)} | ✅ OK |",
        f"| GOP período | {_fmt(kpis['gop'], cfg)} | {_estado_kpi('GOP', alertas)} |",
        f"| Quema diaria | {_fmt(kpis['quema_diaria'], cfg)} | {_estado_kpi('Quema diaria', alertas)} |",
        f"| Pagos pendientes | {_fmt(kpis['pagos_pendientes'], cfg)} | {_estado_kpi('Pagos pendientes', alertas)} |",
    ]

    if alertas:
        lines += ["", "### Alertas activas", ""]
        for a in alertas:
            icono = "🚨" if a["nivel"] == "critico" else "⚠️"
            lines.append(f"- {icono} **{a['kpi']}**: {a['valor']} (umbral: {a['umbral']})")

    return "\n".join(lines)
