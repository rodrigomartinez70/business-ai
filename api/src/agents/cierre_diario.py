"""
Agente de Cierre Diario.

Consolida todas las operaciones del día: ocupación, movimientos,
cobros, ingresos devengados por departamento, gastos y GOP.
Sin LLM — SQL puro sobre datos reales.
"""

import logging
from datetime import date
from decimal import Decimal

from .. import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Cálculo principal
# ─────────────────────────────────────────────────────────────

async def calcular_cierre(fecha: date) -> dict:
    async with config.db_pool.acquire() as conn:

        ocupacion = dict(await conn.fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM reservas
                 WHERE estado = 'checkin'
                   AND fecha_entrada <= $1 AND fecha_salida > $1)   AS en_casa,
                (SELECT COUNT(*) FROM habitaciones WHERE activa = TRUE) AS total_habitaciones
        """, fecha))

        movimientos = dict(await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE fecha_entrada = $1)                          AS checkins,
                COUNT(*) FILTER (WHERE fecha_salida  = $1 AND estado = 'checkout')  AS checkouts,
                COUNT(*) FILTER (WHERE DATE(created_at) = $1
                                   AND estado NOT IN ('cancelada', 'no_show'))      AS reservas_nuevas,
                COUNT(*) FILTER (WHERE DATE(created_at) = $1
                                   AND estado = 'cancelada')                        AS cancelaciones
            FROM reservas
            WHERE fecha_entrada = $1
               OR fecha_salida  = $1
               OR DATE(created_at) = $1
        """, fecha))

        cobros = dict(await conn.fetchrow("""
            SELECT
                COALESCE(SUM(monto) FILTER (WHERE estado = 'pagado'),               0) AS cobrado,
                COALESCE(SUM(monto) FILTER (WHERE estado = 'pendiente'),            0) AS pendiente,
                COUNT(*)            FILTER (WHERE estado = 'pagado')                   AS n_pagos,
                COALESCE(SUM(monto) FILTER (WHERE estado = 'pagado'
                                              AND metodo = 'efectivo'),             0) AS efectivo,
                COALESCE(SUM(monto) FILTER (WHERE estado = 'pagado'
                                              AND metodo = 'tarjeta'),             0) AS tarjeta,
                COALESCE(SUM(monto) FILTER (WHERE estado = 'pagado'
                                              AND metodo = 'transferencia'),       0) AS transferencia
            FROM pagos
            WHERE fecha = $1
        """, fecha))

        hospedaje_devengado = await conn.fetchval("""
            SELECT COALESCE(SUM(total_hospedaje), 0)
            FROM reservas
            WHERE fecha_salida = $1 AND estado = 'checkout'
        """, fecha)

        frigobar = dict(await conn.fetchrow("""
            SELECT
                COALESCE(SUM(total),       0) AS ingresos,
                COALESCE(SUM(costo_total), 0) AS costos,
                COALESCE(SUM(margen),      0) AS margen,
                COUNT(*)                      AS transacciones
            FROM consumos_frigobar
            WHERE fecha = $1
        """, fecha))

        servicios = dict(await conn.fetchrow("""
            SELECT
                COALESCE(SUM(total),       0) AS ingresos,
                COALESCE(SUM(costo_total), 0) AS costos,
                COALESCE(SUM(margen),      0) AS margen,
                COUNT(*)                      AS transacciones
            FROM consumos_servicios
            WHERE fecha = $1
        """, fecha))

        gastos_total = await conn.fetchval("""
            SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha = $1
        """, fecha)

        gastos_cat = [dict(r) for r in await conn.fetch("""
            SELECT
                COALESCE(cg.nombre, 'Sin categoría') AS categoria,
                SUM(g.monto)                          AS monto
            FROM gastos g
            LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
            WHERE g.fecha = $1
            GROUP BY cg.nombre
            ORDER BY monto DESC
        """, fecha)]

        comisiones_ota = [dict(r) for r in await conn.fetch("""
            SELECT
                cv.nombre                                                    AS canal,
                COUNT(*)                                                    AS reservas,
                COALESCE(SUM(r.total_hospedaje), 0)                        AS facturado,
                COALESCE(ROUND(SUM(r.total_hospedaje * cv.comision_pct / 100), 2), 0) AS comision
            FROM reservas r
            JOIN canales_venta cv ON cv.id = r.canal_id
            WHERE r.fecha_salida  = $1
              AND r.estado        = 'checkout'
              AND cv.comision_pct > 0
            GROUP BY cv.nombre
            ORDER BY comision DESC
        """, fecha)]

    # ─── Cálculos derivados ────────────────────────────────────
    def _f(v):
        return float(v) if isinstance(v, Decimal) else float(v or 0)

    en_casa       = int(ocupacion["en_casa"]            or 0)
    total_hab     = int(ocupacion["total_habitaciones"] or 1)
    pct_ocupacion = round(en_casa * 100 / total_hab, 1)

    ing_hospedaje  = _f(hospedaje_devengado)
    ing_frigobar   = _f(frigobar["ingresos"])
    ing_servicios  = _f(servicios["ingresos"])
    total_ingresos = ing_hospedaje + ing_frigobar + ing_servicios

    total_cobrado    = _f(cobros["cobrado"])
    total_gastos     = _f(gastos_total)
    total_comisiones = sum(_f(c["comision"]) for c in comisiones_ota)
    gop              = total_cobrado - total_gastos

    return {
        "fecha": str(fecha),
        "ocupacion": {
            "en_casa":            en_casa,
            "total_habitaciones": total_hab,
            "pct_ocupacion":      pct_ocupacion,
        },
        "movimientos": {
            "checkins":        int(movimientos["checkins"]        or 0),
            "checkouts":       int(movimientos["checkouts"]       or 0),
            "reservas_nuevas": int(movimientos["reservas_nuevas"] or 0),
            "cancelaciones":   int(movimientos["cancelaciones"]   or 0),
        },
        "ingresos": {
            "hospedaje": ing_hospedaje,
            "frigobar":  ing_frigobar,
            "servicios": ing_servicios,
            "total":     total_ingresos,
        },
        "frigobar": {
            "ingresos":      ing_frigobar,
            "costos":        _f(frigobar["costos"]),
            "margen":        _f(frigobar["margen"]),
            "transacciones": int(frigobar["transacciones"] or 0),
        },
        "servicios": {
            "ingresos":      ing_servicios,
            "costos":        _f(servicios["costos"]),
            "margen":        _f(servicios["margen"]),
            "transacciones": int(servicios["transacciones"] or 0),
        },
        "cobros": {
            "cobrado":   total_cobrado,
            "pendiente": _f(cobros["pendiente"]),
            "n_pagos":   int(cobros["n_pagos"] or 0),
            "por_metodo": {
                "efectivo":      _f(cobros["efectivo"]),
                "tarjeta":       _f(cobros["tarjeta"]),
                "transferencia": _f(cobros["transferencia"]),
            },
        },
        "gastos": {
            "total":         total_gastos,
            "por_categoria": [
                {"categoria": r["categoria"], "monto": _f(r["monto"])}
                for r in gastos_cat
            ],
        },
        "comisiones_ota": [
            {
                "canal":    r["canal"],
                "reservas": int(r["reservas"] or 0),
                "facturado":_f(r["facturado"]),
                "comision": _f(r["comision"]),
            }
            for r in comisiones_ota
        ],
        "resumen": {
            "total_ingresos":   total_ingresos,
            "total_cobrado":    total_cobrado,
            "total_gastos":     total_gastos,
            "total_comisiones": total_comisiones,
            "gop":              gop,
            "gop_estado":       "positivo" if gop >= 0 else "negativo",
        },
    }


# ─────────────────────────────────────────────────────────────
# Renderizado
# ─────────────────────────────────────────────────────────────

def _fmt(v: float, cfg: dict) -> str:
    cur = cfg.get("currency", {})
    sym = cur.get("symbol", "$")
    sep = cur.get("thousands_separator", ".")
    return f"{sym}{v:,.0f}".replace(",", sep)


def renderizar_cierre_markdown(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: _fmt(v, cfg)

    ocu = data["ocupacion"]
    mov = data["movimientos"]
    ing = data["ingresos"]
    cob = data["cobros"]
    gas = data["gastos"]
    r   = data["resumen"]

    lines = [
        f"## 📊 Cierre Diario — {biz}",
        f"**Fecha:** {data['fecha']}",
        "",
        "### 🏨 Ocupación",
        "| Huéspedes en casa | Habitaciones totales | Ocupación |",
        "|---|---|---|",
        f"| {ocu['en_casa']} | {ocu['total_habitaciones']} | **{ocu['pct_ocupacion']}%** |",
        "",
        "### 🚪 Movimientos",
        "| Check-ins | Check-outs | Reservas nuevas | Cancelaciones |",
        "|---|---|---|---|",
        f"| {mov['checkins']} | {mov['checkouts']} | {mov['reservas_nuevas']} | {mov['cancelaciones']} |",
        "",
        "### 💰 Ingresos devengados",
        "| Departamento | Monto |",
        "|---|---|",
        f"| Hospedaje | {fm(ing['hospedaje'])} |",
        f"| Frigobar | {fm(ing['frigobar'])} |",
        f"| Servicios | {fm(ing['servicios'])} |",
        f"| **Total** | **{fm(ing['total'])}** |",
        "",
        "### 🏧 Caja del día",
        "| Cobrado | Pendiente | # Pagos |",
        "|---|---|---|",
        f"| **{fm(cob['cobrado'])}** | {fm(cob['pendiente'])} | {cob['n_pagos']} |",
    ]

    pm = cob["por_metodo"]
    metodos = [f"{m.capitalize()}: {fm(v)}" for m, v in pm.items() if v > 0]
    if metodos:
        lines += ["", "*Por método:* " + " · ".join(metodos)]

    if gas["por_categoria"]:
        lines += ["", "### 📋 Gastos del día", "| Categoría | Monto |", "|---|---|"]
        for g in gas["por_categoria"]:
            lines.append(f"| {g['categoria']} | {fm(g['monto'])} |")
        lines.append(f"| **Total** | **{fm(gas['total'])}** |")

    if data["comisiones_ota"]:
        lines += ["", "### 🏪 Comisiones OTA", "| Canal | Reservas | Facturado | Comisión |", "|---|---|---|---|"]
        for c in data["comisiones_ota"]:
            lines.append(f"| {c['canal']} | {c['reservas']} | {fm(c['facturado'])} | {fm(c['comision'])} |")

    gop_icono = "✅" if r["gop"] >= 0 else "🔴"
    lines += [
        "",
        "### 📈 Resultado del día (GOP)",
        "| Cobrado | Gastos | GOP |",
        "|---|---|---|",
        f"| {fm(r['total_cobrado'])} | {fm(r['total_gastos'])} | {gop_icono} **{fm(r['gop'])}** |",
    ]

    return "\n".join(lines)


def build_discord_embed_cierre(data: dict, cfg: dict) -> dict:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: _fmt(v, cfg)

    ocu = data["ocupacion"]
    mov = data["movimientos"]
    ing = data["ingresos"]
    cob = data["cobros"]
    gas = data["gastos"]
    r   = data["resumen"]

    color    = 0x2ECC71 if r["gop"] >= 0 else 0xE74C3C
    gop_icon = "✅" if r["gop"] >= 0 else "🔴"

    pm = cob["por_metodo"]
    metodos_txt = "\n".join(
        f"{m.capitalize()}: {fm(v)}" for m, v in pm.items() if v > 0
    ) or "—"

    gastos_txt = fm(gas["total"])
    if gas["por_categoria"]:
        top = gas["por_categoria"][:3]
        gastos_txt += "\n" + "\n".join(f"{g['categoria']}: {fm(g['monto'])}" for g in top)

    fields = [
        {
            "name":   "🏨 Ocupación",
            "value":  f"**{ocu['pct_ocupacion']}%**\n{ocu['en_casa']} / {ocu['total_habitaciones']} hab.",
            "inline": True,
        },
        {
            "name":   "🚪 Movimientos",
            "value":  (
                f"↓ {mov['checkins']} check-ins\n"
                f"↑ {mov['checkouts']} check-outs\n"
                f"📋 {mov['reservas_nuevas']} nuevas"
                + (f"\n❌ {mov['cancelaciones']} cancel." if mov["cancelaciones"] else "")
            ),
            "inline": True,
        },
        {
            "name":   "💰 Ingresos devengados",
            "value":  (
                f"Hospedaje: {fm(ing['hospedaje'])}\n"
                f"Frigobar: {fm(ing['frigobar'])}\n"
                f"Servicios: {fm(ing['servicios'])}\n"
                f"**Total: {fm(ing['total'])}**"
            ),
            "inline": True,
        },
        {
            "name":   "🏧 Caja",
            "value":  (
                f"Cobrado: **{fm(cob['cobrado'])}**\n"
                f"Pendiente: {fm(cob['pendiente'])}\n"
                + metodos_txt
            ),
            "inline": True,
        },
        {
            "name":   "📋 Gastos",
            "value":  gastos_txt or "—",
            "inline": True,
        },
        {
            "name":   "📈 GOP",
            "value":  f"{gop_icon} **{fm(r['gop'])}**\n(cobrado - gastos)",
            "inline": True,
        },
    ]

    embed: dict = {
        "title":  f"📊 Cierre Diario — {biz} · {data['fecha']}",
        "color":  color,
        "fields": fields,
    }

    if data["comisiones_ota"]:
        ota = " · ".join(
            f"{c['canal']} {fm(c['comision'])}" for c in data["comisiones_ota"]
        )
        embed["footer"] = {"text": f"🏪 Comisiones OTA: {ota}"}

    return {"embeds": [embed]}
