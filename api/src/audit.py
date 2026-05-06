"""
Auditoría de interacciones y reporte de uso del agente.
"""

import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional

from . import config

logger = logging.getLogger(__name__)


async def registrar_auditoria(
    rol:        str,
    pregunta:   str,
    sql:        str,
    filas:      int,
    duracion_ms: int,
    estado:     str,
    tipo_flujo: str,
    modelo_llm: str,
    error_msg:  Optional[str] = None,
) -> None:
    try:
        async with config.db_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO audit_log
                   (rol, pregunta, sql_generado, filas_retorn,
                    duracion_ms, estado, tipo_flujo, modelo_llm, error_msg)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                rol, pregunta, sql, filas,
                duracion_ms, estado, tipo_flujo, modelo_llm, error_msg,
            )
    except Exception as e:
        logger.warning(f"No se pudo registrar en audit_log: {e}")


async def generar_reporte_uso(fecha_inicio: date, fecha_fin: date) -> dict:
    fi = datetime.combine(fecha_inicio, datetime.min.time())
    ff = datetime.combine(fecha_fin,    datetime.max.time())

    async with config.db_pool.acquire() as conn:
        resumen = dict(await conn.fetchrow("""
            SELECT
                COUNT(*)                                                         AS total_consultas,
                COUNT(*) FILTER (WHERE estado = 'ok')                            AS consultas_ok,
                COUNT(*) FILTER (WHERE estado = 'error')                         AS consultas_error,
                ROUND(100.0 * COUNT(*) FILTER (WHERE estado = 'ok')
                      / NULLIF(COUNT(*), 0), 1)                                  AS tasa_exito_pct,
                ROUND(AVG(duracion_ms))                                          AS duracion_promedio_ms,
                ROUND(PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY duracion_ms)) AS duracion_p50_ms,
                ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duracion_ms)) AS duracion_p95_ms,
                MAX(duracion_ms)                                                 AS duracion_max_ms
            FROM audit_log
            WHERE timestamp BETWEEN $1 AND $2
        """, fi, ff))

        por_rol = [dict(r) for r in await conn.fetch("""
            SELECT rol,
                   COUNT(*)                                     AS consultas,
                   ROUND(AVG(duracion_ms))                       AS duracion_promedio_ms,
                   COUNT(*) FILTER (WHERE estado = 'error')     AS errores
            FROM audit_log
            WHERE timestamp BETWEEN $1 AND $2
            GROUP BY rol ORDER BY consultas DESC
        """, fi, ff)]

        por_flujo = [dict(r) for r in await conn.fetch("""
            SELECT tipo_flujo,
                   COUNT(*)                AS consultas,
                   ROUND(AVG(duracion_ms))  AS duracion_promedio_ms
            FROM audit_log
            WHERE timestamp BETWEEN $1 AND $2 AND tipo_flujo IS NOT NULL
            GROUP BY tipo_flujo ORDER BY consultas DESC
        """, fi, ff)]

        por_modelo = [dict(r) for r in await conn.fetch("""
            SELECT modelo_llm,
                   COUNT(*)                AS consultas,
                   ROUND(AVG(duracion_ms))  AS duracion_promedio_ms
            FROM audit_log
            WHERE timestamp BETWEEN $1 AND $2 AND modelo_llm IS NOT NULL
            GROUP BY modelo_llm ORDER BY consultas DESC
        """, fi, ff)]

        por_dia = [dict(r) for r in await conn.fetch("""
            SELECT DATE(timestamp)                               AS dia,
                   COUNT(*)                                      AS consultas,
                   COUNT(*) FILTER (WHERE estado = 'error')     AS errores,
                   ROUND(AVG(duracion_ms))                       AS duracion_promedio_ms
            FROM audit_log
            WHERE timestamp BETWEEN $1 AND $2
            GROUP BY dia ORDER BY dia
        """, fi, ff)]

        errores_recientes = [dict(r) for r in await conn.fetch("""
            SELECT timestamp, rol, tipo_flujo, modelo_llm, duracion_ms, pregunta, error_msg
            FROM audit_log
            WHERE estado = 'error' AND timestamp BETWEEN $1 AND $2
            ORDER BY timestamp DESC LIMIT 10
        """, fi, ff)]

        consultas_recientes = [dict(r) for r in await conn.fetch("""
            SELECT timestamp, rol, tipo_flujo, modelo_llm, duracion_ms, filas_retorn, pregunta
            FROM audit_log
            WHERE timestamp BETWEEN $1 AND $2
            ORDER BY timestamp DESC LIMIT 20
        """, fi, ff)]

    def _serial(v):
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, Decimal):
            return float(v)
        return v

    def _limpiar(rows: list[dict]) -> list[dict]:
        return [{k: _serial(v) for k, v in row.items()} for row in rows]

    return {
        "periodo":             {"inicio": str(fecha_inicio), "fin": str(fecha_fin)},
        "resumen":             {k: _serial(v) for k, v in resumen.items()},
        "por_rol":             _limpiar(por_rol),
        "por_flujo":           _limpiar(por_flujo),
        "por_modelo":          _limpiar(por_modelo),
        "por_dia":             _limpiar(por_dia),
        "errores_recientes":   _limpiar(errores_recientes),
        "consultas_recientes": _limpiar(consultas_recientes),
    }


def renderizar_uso_markdown(reporte: dict, biz_name: str) -> str:
    def fmt_ms(ms) -> str:
        return f"{ms:,} ms" if ms else "—"

    r   = reporte["resumen"]
    fi  = reporte["periodo"]["inicio"]
    ff  = reporte["periodo"]["fin"]

    lineas = [
        f"# Reporte de Uso — {biz_name}",
        f"**Período:** {fi} al {ff}",
        f"**Generado:** {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "## Resumen",
        "| Métrica | Valor |", "|---|---|",
        f"| Total consultas | {r['total_consultas']} |",
        f"| Consultas exitosas | {r['consultas_ok']} |",
        f"| Errores | {r['consultas_error']} |",
        f"| Tasa de éxito | {r['tasa_exito_pct']}% |",
        f"| Latencia promedio | {fmt_ms(r['duracion_promedio_ms'])} |",
        f"| Latencia p50 | {fmt_ms(r['duracion_p50_ms'])} |",
        f"| Latencia p95 | {fmt_ms(r['duracion_p95_ms'])} |",
        f"| Latencia máxima | {fmt_ms(r['duracion_max_ms'])} |",
        "",
        "## Por rol",
        "| Rol | Consultas | Errores | Latencia prom. |", "|---|---|---|---|",
    ]
    for row in reporte["por_rol"]:
        lineas.append(f"| {row['rol']} | {row['consultas']} | {row['errores']} | {fmt_ms(row['duracion_promedio_ms'])} |")

    lineas += ["", "## Por tipo de flujo", "| Flujo | Consultas | Latencia prom. |", "|---|---|---|"]
    for row in reporte["por_flujo"]:
        lineas.append(f"| {row['tipo_flujo'] or '—'} | {row['consultas']} | {fmt_ms(row['duracion_promedio_ms'])} |")

    lineas += ["", "## Por modelo LLM", "| Modelo | Consultas | Latencia prom. |", "|---|---|---|"]
    for row in reporte["por_modelo"]:
        lineas.append(f"| {row['modelo_llm'] or '—'} | {row['consultas']} | {fmt_ms(row['duracion_promedio_ms'])} |")

    lineas += ["", "## Actividad diaria", "| Día | Consultas | Errores | Latencia prom. |", "|---|---|---|---|"]
    for row in reporte["por_dia"]:
        lineas.append(f"| {row['dia']} | {row['consultas']} | {row['errores']} | {fmt_ms(row['duracion_promedio_ms'])} |")

    if reporte["errores_recientes"]:
        lineas += ["", "## Errores recientes", "| Timestamp | Rol | Pregunta | Error |", "|---|---|---|---|"]
        for row in reporte["errores_recientes"]:
            pregunta  = (row["pregunta"] or "")[:60]
            error_msg = (row["error_msg"] or "")[:80]
            lineas.append(f"| {row['timestamp']} | {row['rol']} | {pregunta}… | {error_msg} |")

    return "\n".join(lineas)
