"""
Helpers compartidos de los agentes financieros.

Una sola fuente de verdad para: formato de moneda, conversión numérica,
cálculo de variaciones porcentuales y la paleta de colores de Discord.
Antes estaban duplicados (idénticos) en cada agente.
"""

from decimal import Decimal


# ── Paleta de colores Discord (decimal) ──────────────────────

class COLOR:
    OK      = 0x2ECC71   # verde
    ALERTA  = 0xF39C12   # naranja
    CRITICO = 0xE74C3C   # rojo


# Semáforo de estado → icono / color
SEMAFORO_ICONO = {"ok": "✅", "alerta": "⚠️", "critico": "🚨"}
SEMAFORO_COLOR = {"ok": COLOR.OK, "alerta": COLOR.ALERTA, "critico": COLOR.CRITICO}


# ── Conversión y formato ─────────────────────────────────────

def to_float(v) -> float:
    """Convierte Decimal/None/numérico a float. None → 0.0."""
    return float(v) if isinstance(v, Decimal) else float(v or 0)


def fmt_moneda(v: float, cfg: dict) -> str:
    """Formatea un monto con símbolo y separador de miles del config."""
    cur = cfg.get("currency", {})
    sym = cur.get("symbol", "$")
    sep = cur.get("thousands_separator", ".")
    return f"{sym}{v:,.0f}".replace(",", sep)


# ── Variaciones ──────────────────────────────────────────────

def var_pct(v_actual, v_ref):
    """Variación % de v_actual respecto a v_ref. None si v_ref es 0/None."""
    if v_ref and v_ref != 0:
        return round((v_actual - v_ref) * 100 / abs(v_ref), 1)
    return None


def var_txt(pct, none_label: str = "—") -> str:
    """Texto de variación con flecha. `none_label` se usa cuando pct es None."""
    if pct is None:
        return none_label
    arrow = "▲" if pct > 0 else "▼"
    return f"{arrow} {abs(pct):.1f}%"
