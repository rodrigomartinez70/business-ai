"""
Helpers compartidos de los agentes financieros.

Una sola fuente de verdad para: formato de moneda, conversión numérica,
cálculo de variaciones porcentuales y semáforos de estado.
"""

from decimal import Decimal

import asyncpg


# Semáforo de estado → icono
SEMAFORO_ICONO = {"ok": "✅", "alerta": "⚠️", "critico": "🚨"}


# ── Acceso resiliente a tablas opcionales ────────────────────
# Una empresa puede no tener cierto pack de datos (p. ej. sin POS → sin `pagos`).
# Estas variantes devuelven un default en vez de romper si la tabla no existe.

async def fetchval_opt(conn, sql, *args, default=0):
    try:
        return await conn.fetchval(sql, *args)
    except asyncpg.UndefinedTableError:
        return default


async def fetch_opt(conn, sql, *args):
    try:
        return await conn.fetch(sql, *args)
    except asyncpg.UndefinedTableError:
        return []


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
