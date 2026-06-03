"""
Motor IVA / F29 (horizontal) — débito, crédito, remanente, PPM y retenciones.

Agnóstico al vertical: recibe `ingresos_fn(conn, ini, fin) -> float` que define
qué cuenta como ingreso afecto (hotel: hospedaje+consumos; restaurante: pedidos).
El crédito, remanente, PPM, retención y postergación son comunes a todos.
"""

from datetime import date, timedelta

from src import config
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


def _sumar_meses(d: date, n: int) -> date:
    total = (d.year * 12 + (d.month - 1)) + n
    return date(total // 12, total % 12 + 1, min(d.day, 28))


async def _credito(conn, ini: date, fin: date) -> tuple[float, str]:
    """IVA crédito: facturas registradas (netea notas de crédito) si existen;
    si no, estimación gastos × 19% excluyendo categorías no afectas."""
    docs = await conn.fetchrow("""
        SELECT COUNT(*) AS n,
               COALESCE(SUM(CASE WHEN tipo = 'nota_credito' THEN -monto_iva
                                 ELSE monto_iva END), 0) AS iva
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


async def calcular_iva(conn, hasta: date, ingresos_fn, uf: float | None = None) -> dict:
    """Motor F29. `ingresos_fn(conn, ini, fin)` provee los ingresos afectos del vertical."""
    uf_valor   = uf or c.UF_VALOR
    desde      = hasta - timedelta(days=6)
    inicio_mes = date(hasta.year, hasta.month, 1)

    ing_sem = await ingresos_fn(conn, desde, hasta)
    gastos_semana = dict(await conn.fetchrow(
        "SELECT COALESCE(SUM(monto), 0) AS total_gastos, COUNT(*) AS n_gastos "
        "FROM gastos WHERE fecha BETWEEN $1 AND $2", desde, hasta))
    gasto_sem = to_float(gastos_semana.get("total_gastos", 0))

    ingresos_mes = await ingresos_fn(conn, inicio_mes, hasta)
    iva_debito   = round(ingresos_mes * c.IVA_TASA, 2)
    iva_credito, credito_fuente = await _credito(conn, inicio_mes, hasta)

    remanente = 0.0
    cur = date(hasta.year, 1, 1)
    while cur < inicio_mes:
        fin = _fin_de_mes(cur)
        deb_m = round(await ingresos_fn(conn, cur, fin) * c.IVA_TASA, 2)
        cred_m, _ = await _credito(conn, cur, fin)
        remanente = max(0.0, round(cred_m + remanente - deb_m, 2))
        cur = _siguiente_mes(cur)
    remanente_anterior = remanente

    credito_total       = round(iva_credito + remanente_anterior, 2)
    iva_a_pagar         = max(0.0, round(iva_debito - credito_total, 2))
    remanente_siguiente = max(0.0, round(credito_total - iva_debito, 2))
    saldo_iva           = round(iva_debito - iva_credito, 2)
    saldo_iva_uf        = saldo_iva / uf_valor if uf_valor else 0

    cfg_trib   = (config.get_config() or {}).get("tributario", {})
    ppm_tasa   = float(cfg_trib.get("ppm_tasa", c.PPM_TASA))
    meses_post = int(cfg_trib.get("iva_postergacion_meses", 0) or 0)

    ppm = round(ingresos_mes * ppm_tasa, 2)
    honorarios_mes = to_float(await conn.fetchval("""
        SELECT COALESCE(SUM(g.monto), 0) FROM gastos g
        LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
        WHERE cg.nombre = 'Honorarios' AND g.fecha BETWEEN $1 AND $2
    """, inicio_mes, hasta) or 0)
    retencion = round(honorarios_mes * c.RETENCION_HONORARIOS, 2)
    total_f29 = round(iva_a_pagar + ppm + retencion, 2)

    venc_normal = c.fecha_vencimiento_f29(hasta)
    if meses_post > 0:
        iva_postergado      = True
        vencimiento_iva     = str(_sumar_meses(venc_normal, meses_post))
        total_a_pagar_ahora = round(ppm + retencion, 2)
    else:
        iva_postergado      = False
        vencimiento_iva     = str(venc_normal)
        total_a_pagar_ahora = total_f29

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
            "ppm_tasa_pct":          round(ppm_tasa * 100, 3),
            "retencion_honorarios":  retencion,
            "total_a_pagar":         total_f29,
            "total_a_pagar_ahora":   total_a_pagar_ahora,
            "iva_postergado":        iva_postergado,
            "vencimiento_iva":       vencimiento_iva,
            "monto_estimado":        total_f29,
            "monto_estimado_uf":     round(total_f29 / uf_valor, 2) if uf_valor else 0,
            "vencimiento":           str(venc_normal),
            "dias_para_vencimiento": c.dias_para_vencimiento_f29(hasta),
        },
        "uf_referencia": round(uf_valor, 2),
    }
