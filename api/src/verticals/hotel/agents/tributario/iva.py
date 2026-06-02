"""
Agente IVA / F29 — débito, crédito, remanente, PPM y retenciones.

Calcula los principales componentes del F29 chileno:
  - IVA débito (ventas afectas) y crédito (compras con derecho a crédito).
  - Remanente de crédito fiscal arrastrado de meses anteriores.
  - PPM (pago provisional mensual) sobre ingresos brutos.
  - Retención de boletas de honorarios de terceros.
  - Total a pagar del F29 y su vencimiento.
"""

from datetime import date, timedelta

from src.agents._common import to_float
from . import _common as c


def _fin_de_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _siguiente_mes(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


async def _ingresos(conn, ini: date, fin: date) -> float:
    """Ingresos afectos del período: hospedaje (devengado) + frigobar + servicios.
    Agregados separados para evitar el fan-out del JOIN uno-a-muchos."""
    row = await conn.fetchrow("""
        SELECT
            (SELECT COALESCE(SUM(total_hospedaje), 0) FROM reservas
              WHERE fecha_salida BETWEEN $1 AND $2 AND estado = 'checkout')
          + (SELECT COALESCE(SUM(total), 0) FROM consumos_frigobar WHERE fecha BETWEEN $1 AND $2)
          + (SELECT COALESCE(SUM(total), 0) FROM consumos_servicios WHERE fecha BETWEEN $1 AND $2) AS total
    """, ini, fin)
    return to_float(row["total"])


async def _credito(conn, ini: date, fin: date) -> tuple[float, str]:
    """IVA crédito del período: facturas registradas si existen; si no, estimación
    gastos × 19% excluyendo categorías no afectas (Personal, Honorarios)."""
    docs = await conn.fetchrow("""
        SELECT COUNT(*) AS n, COALESCE(SUM(monto_iva), 0) AS iva
        FROM documentos_tributarios
        WHERE estado = 'registrado' AND fecha BETWEEN $1 AND $2
    """, ini, fin)
    if int(docs["n"]) > 0:
        return to_float(docs["iva"]), "documentos"
    g = await conn.fetchval("""
        SELECT COALESCE(SUM(g.monto), 0) FROM gastos g
        LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
        WHERE g.fecha BETWEEN $1 AND $2 AND COALESCE(cg.nombre, '') <> ALL($3::text[])
    """, ini, fin, list(c.NO_AFECTO_IVA))
    return round(to_float(g) * 0.19, 2), "estimado"


async def calcular_iva(conn, hasta: date, uf: float | None = None) -> dict:
    """Agente IVA/F29. Recibe una conexión scopeada al tenant y la UF del día."""
    uf_valor   = uf or c.UF_VALOR
    desde      = hasta - timedelta(days=6)
    inicio_mes = date(hasta.year, hasta.month, 1)

    # ── Semana actual (display) ─────────────────────────────────────────────
    ing_sem = await _ingresos(conn, desde, hasta)
    gastos_semana = dict(await conn.fetchrow(
        "SELECT COALESCE(SUM(monto), 0) AS total_gastos, COUNT(*) AS n_gastos "
        "FROM gastos WHERE fecha BETWEEN $1 AND $2", desde, hasta))
    gasto_sem = to_float(gastos_semana.get("total_gastos", 0))

    # ── Mes actual: débito y crédito ────────────────────────────────────────
    ingresos_mes = await _ingresos(conn, inicio_mes, hasta)
    iva_debito   = round(ingresos_mes * c.IVA_TASA, 2)
    iva_credito, credito_fuente = await _credito(conn, inicio_mes, hasta)

    # ── Remanente de crédito arrastrado desde meses anteriores del año ──────
    remanente = 0.0
    cur = date(hasta.year, 1, 1)
    while cur < inicio_mes:
        fin = _fin_de_mes(cur)
        deb_m = round(await _ingresos(conn, cur, fin) * c.IVA_TASA, 2)
        cred_m, _ = await _credito(conn, cur, fin)
        remanente = max(0.0, round(cred_m + remanente - deb_m, 2))
        cur = _siguiente_mes(cur)
    remanente_anterior = remanente

    credito_total       = round(iva_credito + remanente_anterior, 2)
    iva_a_pagar         = max(0.0, round(iva_debito - credito_total, 2))
    remanente_siguiente = max(0.0, round(credito_total - iva_debito, 2))
    saldo_iva           = round(iva_debito - iva_credito, 2)   # posición del mes, sin remanente
    saldo_iva_uf        = saldo_iva / uf_valor if uf_valor else 0

    # ── PPM y retención de honorarios ───────────────────────────────────────
    ppm = round(ingresos_mes * c.PPM_TASA, 2)
    honorarios_mes = to_float(await conn.fetchval("""
        SELECT COALESCE(SUM(g.monto), 0) FROM gastos g
        LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
        WHERE cg.nombre = 'Honorarios' AND g.fecha BETWEEN $1 AND $2
    """, inicio_mes, hasta) or 0)
    retencion = round(honorarios_mes * c.RETENCION_HONORARIOS, 2)

    total_f29 = round(iva_a_pagar + ppm + retencion, 2)

    return {
        "semana_actual": {
            "ingresos_afectos": ing_sem,
            "iva_debito":       round(ing_sem * c.IVA_TASA, 2),
            "gastos":           gasto_sem,
            "iva_credito":      round(gasto_sem * c.IVA_TASA, 2),
            "n_gastos":         int(gastos_semana.get("n_gastos", 0)),
        },
        "proximos_7_dias": {
            "iva_debito_estimado":  round(ing_sem * c.IVA_TASA, 2),
            "iva_credito_estimado": round(gasto_sem * c.IVA_TASA, 2),
        },
        "acumulado_mes": {
            "iva_debito_acum":    iva_debito,
            "iva_credito_acum":   iva_credito,
            "iva_credito_fuente": credito_fuente,
            "saldo_iva":          saldo_iva,
            "saldo_iva_uf":       round(saldo_iva_uf, 2),
            "estado":             "deuda" if saldo_iva > 0 else "saldo_a_favor",
        },
        "f29": {
            "periodo":               inicio_mes.strftime("%Y-%m"),
            "iva_debito":            iva_debito,
            "iva_credito":           iva_credito,
            "remanente_anterior":    remanente_anterior,
            "iva_a_pagar":           iva_a_pagar,
            "remanente_siguiente":   remanente_siguiente,
            "ppm":                   ppm,
            "ppm_tasa_pct":          round(c.PPM_TASA * 100, 3),
            "retencion_honorarios":  retencion,
            "total_a_pagar":         total_f29,
            "monto_estimado":        total_f29,   # compat
            "monto_estimado_uf":     round(total_f29 / uf_valor, 2) if uf_valor else 0,
            "vencimiento":           str(c.fecha_vencimiento_f29(hasta)),
            "dias_para_vencimiento": c.dias_para_vencimiento_f29(hasta),
        },
        "uf_referencia": round(uf_valor, 2),
    }
