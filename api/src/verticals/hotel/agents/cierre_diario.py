"""
Agente de Cierre Diario.

Consolida todas las operaciones del día: ocupación, movimientos,
cobros, ingresos devengados por departamento, gastos y GOP.
Sin LLM — SQL puro sobre datos reales.
"""

import logging
from datetime import date

from .... import config
from ....agents._common import COLOR, fmt_moneda, to_float

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Cálculo principal
# ─────────────────────────────────────────────────────────────

async def calcular_cierre(fecha: date) -> dict:
    async with config.db_pool.acquire() as conn:

        ocupacion = dict(await conn.fetchrow("""
            SELECT
                -- Ocupación real de esa noche: cuenta las reservas que efectivamente
                -- ocuparon la habitación, sin importar su estado ACTUAL. Para días
                -- pasados las reservas ya están en 'checkout'; filtrar solo por
                -- 'checkin' daba 0 en el cierre semanal.
                (SELECT COUNT(*) FROM reservas
                 WHERE estado IN ('checkin', 'checkout')
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
    _f = to_float

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
    # GOP devengado: ingresos generados - gastos (base contable)
    gop_devengado    = total_ingresos - total_gastos
    # Resultado caja: lo efectivamente cobrado - gastos (base caja)
    resultado_caja   = total_cobrado - total_gastos

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
            "gop_devengado":    gop_devengado,
            "resultado_caja":   resultado_caja,
            "gop_estado":       "positivo" if gop_devengado >= 0 else "negativo",
        },
    }


async def calcular_cierre_semanal(desde: date, hasta: date) -> dict:
    """
    Agrega los cierres diarios del rango desde→hasta (una semana lun-dom).
    Reutiliza calcular_cierre por día y consolida los totales.
    """
    from datetime import timedelta

    dias = (hasta - desde).days + 1
    cierres = []
    d = desde
    while d <= hasta:
        cierres.append(await calcular_cierre(d))
        d += timedelta(days=1)

    def _suma(path):
        # path: lista de claves anidadas, ej. ["resumen", "total_ingresos"]
        tot = 0.0
        for c in cierres:
            v = c
            for k in path:
                v = v[k]
            tot += v
        return tot

    ocup_validas = [c["ocupacion"]["pct_ocupacion"] for c in cierres]
    ocup_prom    = round(sum(ocup_validas) / len(ocup_validas), 1) if ocup_validas else 0.0

    total_ingresos = _suma(["resumen", "total_ingresos"])
    total_gastos   = _suma(["resumen", "total_gastos"])
    gop_devengado  = _suma(["resumen", "gop_devengado"])

    return {
        "periodo": {"inicio": str(desde), "fin": str(hasta), "dias": dias},
        "totales": {
            "ingresos":       total_ingresos,
            "cobrado":        _suma(["resumen", "total_cobrado"]),
            "gastos":         total_gastos,
            "comisiones_ota": _suma(["resumen", "total_comisiones"]),
            "gop_devengado":  gop_devengado,
            "resultado_caja": _suma(["resumen", "resultado_caja"]),
            "gop_estado":     "positivo" if gop_devengado >= 0 else "negativo",
        },
        "movimientos": {
            "checkins":        int(_suma(["movimientos", "checkins"])),
            "checkouts":       int(_suma(["movimientos", "checkouts"])),
            "reservas_nuevas": int(_suma(["movimientos", "reservas_nuevas"])),
            "cancelaciones":   int(_suma(["movimientos", "cancelaciones"])),
        },
        "ocupacion_promedio_pct": ocup_prom,
        "por_dia": [
            {
                "fecha":          c["fecha"],
                "ocupacion_pct":  c["ocupacion"]["pct_ocupacion"],
                "ingresos":       c["resumen"]["total_ingresos"],
                "cobrado":        c["resumen"]["total_cobrado"],
                "gop_devengado":  c["resumen"]["gop_devengado"],
            }
            for c in cierres
        ],
    }


# ─────────────────────────────────────────────────────────────
# Renderizado
# ─────────────────────────────────────────────────────────────

def renderizar_cierre_markdown(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)

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

    gop_icono = "✅" if r["gop_devengado"] >= 0 else "🔴"
    lines += [
        "",
        "### 📈 Resultado del día",
        "| | Monto | Base |",
        "|---|---|---|",
        f"| GOP devengado | {gop_icono} **{fm(r['gop_devengado'])}** | Ingresos - Gastos |",
        f"| Resultado caja | {'✅' if r['resultado_caja'] >= 0 else '🔴'} **{fm(r['resultado_caja'])}** | Cobrado - Gastos |",
    ]

    return "\n".join(lines)


def build_discord_embed_cierre(data: dict, cfg: dict) -> dict:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)

    ocu = data["ocupacion"]
    mov = data["movimientos"]
    ing = data["ingresos"]
    cob = data["cobros"]
    gas = data["gastos"]
    r   = data["resumen"]

    color    = COLOR.OK if r["gop_devengado"] >= 0 else COLOR.CRITICO
    gop_icon = "✅" if r["gop_devengado"] >= 0 else "🔴"

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
            "name":   "📈 Resultado",
            "value":  (
                f"GOP devengado: {gop_icon} **{fm(r['gop_devengado'])}**\n"
                f"Resultado caja: {'✅' if r['resultado_caja'] >= 0 else '🔴'} {fm(r['resultado_caja'])}"
            ),
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
