"""
Agente de Indicadores y Alertas Tempranas.

Calcula KPIs sin LLM (SQL puro) ejecutando las queries definidas en config.yaml.
Cada KPI en config.yaml puede tener:
  - sql:           query que retorna un único valor escalar
  - unidad:        "%" | "moneda" | "número"
  - umbral_minimo: alerta si valor < umbral
  - umbral_maximo: alerta si valor > umbral
Las variables {fecha_inicio}, {fecha_fin} y {periodo_dias} se sustituyen automáticamente.
"""

import logging
from datetime import date, timedelta

from .. import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Cálculo de KPIs
# ─────────────────────────────────────────────────────────────

async def calcular_kpis(periodo_dias: int) -> list[dict]:
    """Ejecuta el SQL de cada KPI configurado y retorna la lista de resultados."""
    fecha_fin    = date.today()
    fecha_inicio = fecha_fin - timedelta(days=periodo_dias - 1)

    kpis_cfg = [k for k in config.CONFIG.get("kpis", []) if "sql" in k]
    resultados: list[dict] = []

    for kpi in kpis_cfg:
        sql = kpi["sql"].format(
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            periodo_dias=periodo_dias,
        )
        try:
            async with config.db_pool.acquire() as conn:
                valor = await conn.fetchval(sql)
            resultados.append({
                "name":                  kpi["name"],
                "valor":                 float(valor) if valor is not None else None,
                "unidad":                kpi.get("unidad", "número"),
                "umbral_minimo":         kpi.get("umbral_minimo"),
                "umbral_maximo":         kpi.get("umbral_maximo"),
                "umbral_warning_minimo": kpi.get("umbral_warning_minimo"),
                "umbral_critico_minimo": kpi.get("umbral_critico_minimo"),
                "umbral_warning_maximo": kpi.get("umbral_warning_maximo"),
                "umbral_critico_maximo": kpi.get("umbral_critico_maximo"),
            })
        except Exception as e:
            logger.warning(f"KPI '{kpi['name']}' falló: {e}")
            resultados.append({
                "name":   kpi["name"],
                "valor":  None,
                "unidad": kpi.get("unidad", "número"),
                "error":  str(e),
            })

    return resultados


# ─────────────────────────────────────────────────────────────
# Evaluación de umbrales
# ─────────────────────────────────────────────────────────────

def evaluar_umbrales(kpis: list[dict]) -> list[dict]:
    """Compara cada KPI contra sus umbrales → lista de alertas.

    Soporta umbrales de dos niveles:
      umbral_critico_minimo / umbral_warning_minimo (o umbral_minimo como alias)
      umbral_critico_maximo / umbral_warning_maximo (o umbral_maximo como alias)
    """
    alertas: list[dict] = []

    for kpi in kpis:
        valor = kpi.get("valor")
        if valor is None:
            continue

        crit_min = kpi.get("umbral_critico_minimo")
        warn_min = kpi.get("umbral_warning_minimo") or kpi.get("umbral_minimo")
        crit_max = kpi.get("umbral_critico_maximo")
        warn_max = kpi.get("umbral_warning_maximo") or kpi.get("umbral_maximo")

        if crit_min is not None and valor < crit_min:
            alertas.append({"kpi": kpi["name"], "valor": valor, "umbral": f"mínimo {crit_min}", "nivel": "critico"})
        elif warn_min is not None and valor < warn_min:
            alertas.append({"kpi": kpi["name"], "valor": valor, "umbral": f"mínimo {warn_min}", "nivel": "alerta"})

        if crit_max is not None and valor > crit_max:
            alertas.append({"kpi": kpi["name"], "valor": valor, "umbral": f"máximo {crit_max}", "nivel": "critico"})
        elif warn_max is not None and valor > warn_max:
            alertas.append({"kpi": kpi["name"], "valor": valor, "umbral": f"máximo {warn_max}", "nivel": "alerta"})

    return alertas


# ─────────────────────────────────────────────────────────────
# Renderizado del reporte
# ─────────────────────────────────────────────────────────────

def _fmt(valor: float, cfg: dict) -> str:
    currency  = cfg.get("currency", {})
    symbol    = currency.get("symbol", "$")
    sep_miles = currency.get("thousands_separator", ".")
    sep_dec   = currency.get("decimal_separator", ",")
    decimales = int(currency.get("decimal_places", 0))

    formatted = f"{valor:,.{decimales}f}"
    formatted = (
        formatted
        .replace(",", "\x00")
        .replace(".", sep_dec)
        .replace("\x00", sep_miles)
    )
    return f"{symbol}{formatted}"


def _fmt_kpi(kpi: dict, cfg: dict) -> str:
    valor = kpi.get("valor")
    if valor is None:
        return "—"
    unidad = kpi.get("unidad", "número")
    if unidad == "moneda":
        return _fmt(valor, cfg)
    if unidad == "%":
        return f"{valor:.1f}%"
    return f"{valor:,.0f}" if valor == int(valor) else f"{valor:,.2f}"


def _estado_kpi(kpi_name: str, alertas: list[dict]) -> str:
    match = next((a for a in alertas if a["kpi"] == kpi_name), None)
    if not match:
        return "✅ OK"
    icono = "🚨" if match["nivel"] == "critico" else "⚠️"
    return f"{icono} {match['umbral']}"


def renderizar_reporte(kpis: list[dict], alertas: list[dict], cfg: dict, periodo_dias: int) -> str:
    biz_name = cfg.get("business", {}).get("name", "Negocio")
    fecha_fin    = date.today()
    fecha_inicio = fecha_fin - timedelta(days=periodo_dias - 1)

    tiene_critico  = any(a["nivel"] == "critico" for a in alertas)
    estado_general = "CRÍTICO" if tiene_critico else "ALERTA" if alertas else "OK"
    icono_gral     = "🚨" if tiene_critico else "⚠️" if alertas else "✅"

    lines = [
        f"## {icono_gral} KPIs — {biz_name}",
        f"**Período:** {fecha_inicio} → {fecha_fin} ({periodo_dias} días)",
        f"**Estado general:** {estado_general}",
        "",
        "| Indicador | Valor | Estado |",
        "|-----------|-------|--------|",
    ]

    for kpi in kpis:
        if kpi.get("error"):
            estado = "❌ Error"
        elif kpi.get("valor") is not None:
            estado = _estado_kpi(kpi["name"], alertas)
        else:
            estado = "— sin datos"
        lines.append(f"| {kpi['name']} | {_fmt_kpi(kpi, cfg)} | {estado} |")

    if alertas:
        lines += ["", "### Alertas activas", ""]
        for a in alertas:
            icono = "🚨" if a["nivel"] == "critico" else "⚠️"
            lines.append(f"- {icono} **{a['kpi']}**: {a['valor']} (umbral: {a['umbral']})")

    return "\n".join(lines)
