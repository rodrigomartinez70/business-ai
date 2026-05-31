"""
Agente de Control de Gastos.

Compara gastos del período actual vs período anterior por categoría.
Detecta variaciones anómalas, gastos sin clasificar y proveedores nuevos.
Sin LLM — SQL puro.
"""

import logging
from datetime import date, timedelta

from .. import config
from ._common import COLOR, fmt_moneda, to_float, var_txt

logger = logging.getLogger(__name__)

# Umbrales de alerta por variación vs período anterior
UMBRAL_ALERTA_PCT   = 20   # ⚠️  variación ≥ 20%
UMBRAL_CRITICO_PCT  = 50   # 🚨 variación ≥ 50%


# ─────────────────────────────────────────────────────────────
# Cálculo principal
# ─────────────────────────────────────────────────────────────

async def calcular_control_gastos(
    fecha_inicio: date,
    fecha_fin:    date,
) -> dict:
    dias        = (fecha_fin - fecha_inicio).days + 1
    prev_inicio = fecha_inicio - timedelta(days=dias)
    prev_fin    = fecha_inicio - timedelta(days=1)

    async with config.db_pool.acquire() as conn:

        # 1. Resumen por categoría: período actual vs anterior
        cat_rows = [dict(r) for r in await conn.fetch("""
            WITH actual AS (
                SELECT
                    COALESCE(cg.nombre, 'Sin categoría') AS categoria,
                    SUM(g.monto)                          AS monto,
                    COUNT(*)                              AS n_gastos
                FROM gastos g
                LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
                WHERE g.fecha BETWEEN $1 AND $2
                GROUP BY cg.nombre
            ),
            anterior AS (
                SELECT
                    COALESCE(cg.nombre, 'Sin categoría') AS categoria,
                    SUM(g.monto)                          AS monto
                FROM gastos g
                LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
                WHERE g.fecha BETWEEN $3 AND $4
                GROUP BY cg.nombre
            )
            SELECT
                COALESCE(a.categoria, p.categoria)    AS categoria,
                COALESCE(a.monto,    0)               AS monto_actual,
                COALESCE(a.n_gastos, 0)               AS n_gastos,
                COALESCE(p.monto,    0)               AS monto_anterior,
                CASE
                    WHEN COALESCE(p.monto, 0) = 0 THEN NULL
                    ELSE ROUND(
                        (COALESCE(a.monto, 0) - COALESCE(p.monto, 0))
                        * 100.0 / p.monto, 1
                    )
                END AS variacion_pct
            FROM actual a
            FULL OUTER JOIN anterior p ON a.categoria = p.categoria
            ORDER BY COALESCE(a.monto, 0) DESC
        """, fecha_inicio, fecha_fin, prev_inicio, prev_fin)]

        # 2. Totales globales
        totales = dict(await conn.fetchrow("""
            SELECT
                COALESCE(SUM(monto) FILTER (WHERE fecha BETWEEN $1 AND $2), 0) AS total_actual,
                COALESCE(SUM(monto) FILTER (WHERE fecha BETWEEN $3 AND $4), 0) AS total_anterior,
                COUNT(*)            FILTER (WHERE fecha BETWEEN $1 AND $2)     AS n_gastos_actual,
                COUNT(*)            FILTER (WHERE fecha BETWEEN $3 AND $4)     AS n_gastos_anterior
            FROM gastos
            WHERE fecha BETWEEN $3 AND $2
        """, fecha_inicio, fecha_fin, prev_inicio, prev_fin))

        # 3. Gastos sin categoría en el período actual
        sin_cat = dict(await conn.fetchrow("""
            SELECT
                COUNT(*)           AS n,
                COALESCE(SUM(monto), 0) AS total
            FROM gastos
            WHERE categoria_id IS NULL
              AND fecha BETWEEN $1 AND $2
        """, fecha_inicio, fecha_fin))

        # 4. Proveedores nuevos (aparecen por primera vez en el período actual)
        proveedores_nuevos = [dict(r) for r in await conn.fetch("""
            SELECT
                g.proveedor,
                SUM(g.monto)  AS monto_total,
                COUNT(*)      AS n_gastos
            FROM gastos g
            WHERE g.fecha    BETWEEN $1 AND $2
              AND g.proveedor IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM gastos g2
                  WHERE g2.proveedor = g.proveedor
                    AND g2.fecha < $1
              )
            GROUP BY g.proveedor
            ORDER BY monto_total DESC
        """, fecha_inicio, fecha_fin)]

        # 5. Top 5 gastos individuales del período
        top_gastos = [dict(r) for r in await conn.fetch("""
            SELECT
                g.fecha,
                COALESCE(cg.nombre, 'Sin categoría') AS categoria,
                g.descripcion,
                g.monto,
                g.proveedor
            FROM gastos g
            LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
            WHERE g.fecha BETWEEN $1 AND $2
            ORDER BY g.monto DESC
            LIMIT 5
        """, fecha_inicio, fecha_fin)]

    # ─── Cálculos derivados ────────────────────────────────────
    _f = to_float

    total_actual   = _f(totales["total_actual"])
    total_anterior = _f(totales["total_anterior"])
    variacion_total = (
        round((total_actual - total_anterior) * 100 / total_anterior, 1)
        if total_anterior > 0 else None
    )

    categorias = [
        {
            "categoria":       r["categoria"],
            "monto_actual":    _f(r["monto_actual"]),
            "monto_anterior":  _f(r["monto_anterior"]),
            "n_gastos":        int(r["n_gastos"] or 0),
            "variacion_pct":   float(r["variacion_pct"]) if r["variacion_pct"] is not None else None,
        }
        for r in cat_rows
    ]

    # Alertas: categorías con variación significativa
    alertas = []
    for c in categorias:
        pct = c["variacion_pct"]
        if pct is None or c["monto_actual"] == 0:
            continue
        if abs(pct) >= UMBRAL_CRITICO_PCT:
            nivel = "critico"
        elif abs(pct) >= UMBRAL_ALERTA_PCT:
            nivel = "alerta"
        else:
            continue
        alertas.append({
            "categoria":     c["categoria"],
            "variacion_pct": pct,
            "monto_actual":  c["monto_actual"],
            "monto_anterior":c["monto_anterior"],
            "nivel":         nivel,
        })
    alertas.sort(key=lambda x: abs(x["variacion_pct"]), reverse=True)

    return {
        "periodo": {
            "inicio":       str(fecha_inicio),
            "fin":          str(fecha_fin),
            "dias":         dias,
            "prev_inicio":  str(prev_inicio),
            "prev_fin":     str(prev_fin),
        },
        "resumen": {
            "total_actual":    total_actual,
            "total_anterior":  total_anterior,
            "variacion_pct":   variacion_total,
            "n_gastos_actual": int(totales["n_gastos_actual"] or 0),
            "n_gastos_ant":    int(totales["n_gastos_anterior"] or 0),
        },
        "categorias":          categorias,
        "alertas":             alertas,
        "sin_categoria": {
            "n":     int(sin_cat["n"] or 0),
            "total": _f(sin_cat["total"]),
        },
        "proveedores_nuevos":  [
            {
                "proveedor":  r["proveedor"],
                "monto_total":_f(r["monto_total"]),
                "n_gastos":   int(r["n_gastos"] or 0),
            }
            for r in proveedores_nuevos
        ],
        "top_gastos": [
            {
                "fecha":      str(r["fecha"]),
                "categoria":  r["categoria"],
                "descripcion":r["descripcion"],
                "monto":      _f(r["monto"]),
                "proveedor":  r["proveedor"],
            }
            for r in top_gastos
        ],
    }


async def calcular_gastos_analitico(hasta: date, ipc_acum_pct: float | None = None) -> dict:
    """
    Vista analítica de gastos (12 meses) para el CFO:
      - serie mensual de gasto
      - crecimiento del gasto (prom. últimos 3 meses vs primeros 3 de la ventana)
        contrastado con la inflación acumulada (IPC) → ¿los costos suben sobre la inflación?
      - top categorías y top proveedores del período

    `ipc_acum_pct` es la inflación acumulada 12m (de economia.obtener_ipc); si se
    pasa, se calcula la brecha gasto-vs-inflación.
    """
    async with config.db_pool.acquire() as conn:
        serie_rows = [dict(r) for r in await conn.fetch("""
            SELECT to_char(date_trunc('month', fecha), 'YYYY-MM') AS mes,
                   SUM(monto)                                     AS total
            FROM gastos
            WHERE fecha > ($1::date - INTERVAL '12 months') AND fecha <= $1
            GROUP BY 1 ORDER BY 1
        """, hasta)]

        cat_rows = [dict(r) for r in await conn.fetch("""
            SELECT COALESCE(cg.nombre, 'Sin categoría') AS categoria,
                   SUM(g.monto)                          AS monto
            FROM gastos g
            LEFT JOIN categorias_gasto cg ON cg.id = g.categoria_id
            WHERE g.fecha > ($1::date - INTERVAL '12 months') AND g.fecha <= $1
            GROUP BY 1 ORDER BY monto DESC
        """, hasta)]

        prov_rows = [dict(r) for r in await conn.fetch("""
            SELECT proveedor,
                   SUM(monto) AS monto,
                   COUNT(*)   AS n
            FROM gastos
            WHERE fecha > ($1::date - INTERVAL '12 months') AND fecha <= $1
              AND proveedor IS NOT NULL AND proveedor <> ''
            GROUP BY proveedor ORDER BY monto DESC LIMIT 5
        """, hasta)]

    serie = [{"mes": r["mes"], "monto": to_float(r["total"])} for r in serie_rows]
    montos = [s["monto"] for s in serie]
    total_12m = sum(montos)
    n = len(serie)
    prom_mensual = round(total_12m / n, 2) if n else 0.0

    # Crecimiento del gasto: promedio de los 3 meses más recientes vs los 3 más
    # antiguos de la ventana (suaviza el ruido mensual). Requiere ≥6 meses.
    crecimiento_pct = None
    if n >= 6:
        prom_ini = sum(montos[:3]) / 3
        prom_fin = sum(montos[-3:]) / 3
        if prom_ini > 0:
            crecimiento_pct = round((prom_fin - prom_ini) * 100 / prom_ini, 1)

    brecha_pp = None
    if crecimiento_pct is not None and ipc_acum_pct is not None:
        brecha_pp = round(crecimiento_pct - ipc_acum_pct, 1)

    return {
        "periodo":        {"fin": str(hasta), "meses": n},
        "serie_mensual":  serie,
        "gasto_total_12m": total_12m,
        "gasto_prom_mensual": prom_mensual,
        "crecimiento_pct": crecimiento_pct,
        "ipc_acum_pct":    ipc_acum_pct,
        "brecha_pp":       brecha_pp,   # gasto - inflación; >0 = costos suben sobre IPC
        "top_categorias": [
            {"categoria": r["categoria"], "monto": to_float(r["monto"]),
             "pct": round(to_float(r["monto"]) * 100 / total_12m, 1) if total_12m else 0}
            for r in cat_rows[:5]
        ],
        "top_proveedores": [
            {"proveedor": r["proveedor"], "monto": to_float(r["monto"]), "n": int(r["n"])}
            for r in prov_rows
        ],
    }


# ─────────────────────────────────────────────────────────────
# Renderizado
# ─────────────────────────────────────────────────────────────

def _variacion_txt(pct):
    return var_txt(pct, "nuevo")


def _nivel_icono(nivel: str) -> str:
    return "🚨" if nivel == "critico" else "⚠️"


def renderizar_control_gastos_markdown(data: dict, cfg: dict) -> str:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)
    p   = data["periodo"]
    r   = data["resumen"]

    var_txt = _variacion_txt(r["variacion_pct"])
    lines = [
        f"## 📋 Control de Gastos — {biz}",
        f"**Período:** {p['inicio']} → {p['fin']} ({p['dias']} días)",
        f"**Comparado con:** {p['prev_inicio']} → {p['prev_fin']}",
        "",
        "### Resumen",
        "| Período | Total | Gastos |",
        "|---|---|---|",
        f"| Actual | **{fm(r['total_actual'])}** | {r['n_gastos_actual']} |",
        f"| Anterior | {fm(r['total_anterior'])} | {r['n_gastos_ant']} |",
        f"| Variación | **{var_txt}** | — |",
    ]

    if data["alertas"]:
        lines += ["", "### 🔔 Alertas de variación"]
        for a in data["alertas"]:
            icono = _nivel_icono(a["nivel"])
            lines.append(
                f"- {icono} **{a['categoria']}**: {fm(a['monto_actual'])} "
                f"({_variacion_txt(a['variacion_pct'])} vs {fm(a['monto_anterior'])} anterior)"
            )

    lines += ["", "### Desglose por categoría",
              "| Categoría | Actual | Anterior | Variación |",
              "|---|---|---|---|"]
    for c in data["categorias"]:
        lines.append(
            f"| {c['categoria']} | {fm(c['monto_actual'])} | "
            f"{fm(c['monto_anterior'])} | {_variacion_txt(c['variacion_pct'])} |"
        )

    if data["top_gastos"]:
        lines += ["", "### Top 5 gastos del período",
                  "| Fecha | Categoría | Descripción | Monto |",
                  "|---|---|---|---|"]
        for g in data["top_gastos"]:
            lines.append(
                f"| {g['fecha']} | {g['categoria']} | "
                f"{(g['descripcion'] or '')[:40]} | {fm(g['monto'])} |"
            )

    extras = []
    if data["sin_categoria"]["n"] > 0:
        sc = data["sin_categoria"]
        extras.append(
            f"⚠️ **{sc['n']} gastos sin categoría** por {fm(sc['total'])} — requieren clasificación"
        )
    if data["proveedores_nuevos"]:
        pvs = ", ".join(p["proveedor"] for p in data["proveedores_nuevos"][:3])
        extras.append(f"🆕 **Proveedores nuevos:** {pvs}")
    if extras:
        lines += ["", "### Notas"] + [f"- {e}" for e in extras]

    return "\n".join(lines)


def build_discord_embed_control_gastos(data: dict, cfg: dict) -> dict:
    biz = cfg.get("business", {}).get("name", "Negocio")
    fm  = lambda v: fmt_moneda(v, cfg)
    p   = data["periodo"]
    r   = data["resumen"]

    tiene_critico = any(a["nivel"] == "critico" for a in data["alertas"])
    tiene_alerta  = bool(data["alertas"])
    color = COLOR.CRITICO if tiene_critico else (COLOR.ALERTA if tiene_alerta else COLOR.OK)

    var_txt = _variacion_txt(r["variacion_pct"])

    # Campo de categorías (máx 3 para no saturar)
    cat_lines = []
    for c in data["categorias"][:6]:
        if c["monto_actual"] == 0 and c["monto_anterior"] == 0:
            continue
        var = _variacion_txt(c["variacion_pct"])
        cat_lines.append(f"{c['categoria']}: **{fm(c['monto_actual'])}** ({var})")
    categorias_txt = "\n".join(cat_lines) or "—"

    fields = [
        {
            "name":   "💰 Gasto total",
            "value":  (
                f"Actual: **{fm(r['total_actual'])}**\n"
                f"Anterior: {fm(r['total_anterior'])}\n"
                f"Variación: **{var_txt}**"
            ),
            "inline": True,
        },
        {
            "name":   "📊 Por categoría",
            "value":  categorias_txt,
            "inline": True,
        },
    ]

    if data["alertas"]:
        alerta_lines = [
            f"{_nivel_icono(a['nivel'])} **{a['categoria']}**: "
            f"{fm(a['monto_actual'])} ({_variacion_txt(a['variacion_pct'])})"
            for a in data["alertas"]
        ]
        fields.append({
            "name":   "🔔 Alertas",
            "value":  "\n".join(alerta_lines),
            "inline": False,
        })

    footer_parts = []
    if data["sin_categoria"]["n"] > 0:
        sc = data["sin_categoria"]
        footer_parts.append(f"⚠️ {sc['n']} sin categoría ({fm(sc['total'])})")
    if data["proveedores_nuevos"]:
        pvs = ", ".join(pv["proveedor"] for pv in data["proveedores_nuevos"][:3])
        footer_parts.append(f"🆕 Nuevos: {pvs}")

    embed: dict = {
        "title":  f"📋 Control de Gastos — {biz} · {p['inicio']} → {p['fin']}",
        "color":  color,
        "fields": fields,
    }
    if footer_parts:
        embed["footer"] = {"text": " · ".join(footer_parts)}

    return {"embeds": [embed]}
