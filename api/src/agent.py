"""
Lógica del agente text-to-SQL.
Maneja la interacción con LLMs (Claude y Ollama), generación de SQL,
planificación multi-paso y síntesis de resultados.
"""

import re
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Optional

import httpx
import asyncpg
import anthropic
from fastapi import HTTPException

from . import config

logger = logging.getLogger(__name__)

# Carga guidelines de SQL desde archivo externo (opcional)
_GUIDELINES_PATH = Path(__file__).parent.parent / "sql_guidelines.md"

def _load_guidelines() -> str:
    if _GUIDELINES_PATH.exists():
        return "\n\n" + _GUIDELINES_PATH.read_text(encoding="utf-8")
    return ""

SQL_GUIDELINES = _load_guidelines()


# ─── Ollama ──────────────────────────────────────────────────

async def llamar_ollama(prompt: str, system: str = "") -> str:
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1024},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(f"{config.OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="El modelo tardó demasiado.")
        except Exception:
            raise HTTPException(status_code=502, detail="El servicio de IA no está disponible.")


# ─── Utilidades SQL ──────────────────────────────────────────

def _agregar_wildcards_ilike(sql: str) -> str:
    def reemplazar(m):
        v = m.group(1)
        if not v.startswith("%"):
            v = f"%{v}"
        if not v.endswith("%"):
            v = f"{v}%"
        return f"ILIKE '{v}'"
    return re.sub(r"ILIKE\s+'([^']*)'", reemplazar, sql, flags=re.IGNORECASE)


def _limpiar_sql(sql: str) -> str:
    lineas = [re.sub(r"--.*$", "", line) for line in sql.splitlines()]
    limpio = re.sub(r";\s*(?=\S)", " ", "\n".join(lineas))
    return limpio.rstrip("; \n").strip()


def extraer_sql(texto: str) -> str:
    m = re.search(r"```(?:sql)?\s*([\s\S]*?)```", texto, re.IGNORECASE)
    if m:
        return _agregar_wildcards_ilike(_limpiar_sql(m.group(1).strip()))
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        if linea.strip().upper().startswith("SELECT"):
            return _agregar_wildcards_ilike(_limpiar_sql("\n".join(lineas[i:])))
    return _agregar_wildcards_ilike(_limpiar_sql(texto.strip()))


def validar_sql(sql: str) -> None:
    sql_upper = sql.upper().strip()
    if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
        raise HTTPException(status_code=400, detail="Solo se permiten consultas SELECT.")
    for op in ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE"]:
        if re.search(r"\b" + op + r"\b", sql_upper):
            raise HTTPException(status_code=400, detail=f"Operación no permitida: {op}")


# ─── Planificación multi-paso ────────────────────────────────

async def generar_plan(pregunta: str, rol: str) -> Optional[list[dict]]:
    """
    Pide a Claude un plan JSON con N pasos SQL.
    Claude solo ve el schema — nunca datos reales.
    Retorna lista de pasos o None si la pregunta es simple.
    """
    schema   = config.schema_for(rol)
    biz_name = config.biz("name", "negocio")
    aliases  = config.aliases_text()

    system = f"""Eres un planificador de consultas SQL para {biz_name}. Tu tarea es decidir si una pregunta requiere múltiples queries o solo una.

REGLA PRINCIPAL: Sé conservador. La mayoría de preguntas son SIMPLES. Solo usa el plan multi-paso cuando sea estrictamente necesario.

Si la pregunta es SIMPLE → responde con {{"pasos": null}}
Ejemplos SIMPLES (devuelve null):
- totales, promedios, conteos de UNA métrica
- listas o rankings de una tabla
- filtros por fecha, tipo, estado en una sola tabla
- cualquier pregunta que un JOIN o GROUP BY simple resuelva
- datos de MÚLTIPLES AÑOS o MESES → una sola query con IN (...) y GROUP BY año/mes (NO es plan multi-paso)
- "ventas por canal en 2025 y 2026" → SIMPLE: SELECT ... WHERE año IN (2025,2026) GROUP BY canal, año

Si la pregunta es COMPLEJA → responde con el plan JSON:
{{
  "pasos": [
    {{"id": 1, "proposito": "descripción breve", "sql": "SELECT ..."}},
    {{"id": 2, "proposito": "descripción breve", "sql": "SELECT ..."}}
  ]
}}
Ejemplos COMPLEJOS (usa plan):
- COMPARACIÓN entre dos períodos distintos
- EXPLICACIÓN de causas de cambios en KPIs
- CRUCE de múltiples métricas de tablas incompatibles entre sí
- RANKING que necesita datos de 3 o más tablas

Reglas CRÍTICAS del plan:
- Máximo 4 pasos
- Cada SQL debe ser SELECT válido con LIMIT 100
{aliases}

ANTI-CARTESIANO — regla más importante:
Cada paso usa UNA SOLA TABLA como fuente principal.
NUNCA hacer JOIN entre dos tablas con relación 1-a-muchos en el mismo SELECT (multiplica los montos).
Si necesitas combinar datos de tablas con relación 1-a-muchos: son pasos SEPARADOS.
Los únicos JOINs seguros son los de dimensión (1-a-1).

- Si la pregunta requiere datos inexistentes en el schema: {{"pasos": null, "sin_datos": "motivo"}}
- Responde SOLO con el JSON, sin texto adicional
{SQL_GUIDELINES}"""

    prompt = f"Schema:\n{schema}\n\nPregunta: {pregunta}"

    if not (config.ANTHROPIC_KEY and config.ANTHROPIC_KEY != "sk-ant-tu-clave-aqui"):
        return None

    try:
        client  = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_KEY)
        message = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = message.content[0].text.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", texto)
        if m:
            texto = m.group(1).strip()
        plan = json.loads(texto)

        if plan.get("sin_datos"):
            raise HTTPException(status_code=422, detail=plan["sin_datos"])

        pasos = plan.get("pasos")
        if not pasos:
            return None

        for paso in pasos:
            if "sql" not in paso or "proposito" not in paso:
                return None
            validar_sql(paso["sql"])

        logger.info(f"Plan generado: {len(pasos)} pasos")
        return pasos[:4]

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Plan falló, usando SQL simple: {e}")
        return None


async def ejecutar_plan(pasos: list[dict], rol: str, pregunta: str) -> list[dict]:
    resultados: list[dict] = []
    consecutivos_fallidos  = 0

    for paso in pasos:
        sql       = paso["sql"]
        proposito = paso["proposito"]
        logger.info(f"[Plan paso] {proposito} | SQL: {sql[:200]}")
        try:
            datos = await ejecutar_sql(sql, rol, pregunta)
            if len(datos) > 20:
                datos = [{"resumen": f"{len(datos)} registros encontrados", "muestra": datos[:3]}]
            resultados.append({"proposito": proposito, "datos": datos, "ok": True})
            consecutivos_fallidos = 0
        except Exception as e:
            logger.warning(f"Paso '{proposito}' falló: {e}")
            resultados.append({"proposito": proposito, "datos": [], "ok": False, "error": str(e)})
            consecutivos_fallidos += 1
            if consecutivos_fallidos >= 2:
                logger.error("2 pasos consecutivos fallidos — abortando plan")
                break

    return resultados


# ─── Síntesis local (Ollama) ─────────────────────────────────

def _formatear_tabla(datos: list[dict]) -> str:
    if not datos:
        return "(sin resultados)"
    lineas = []
    for fila in datos:
        partes = [
            f"{k}: {float(v):,.2f}" if isinstance(v, (int, float, Decimal)) else f"{k}: {v}"
            for k, v in fila.items()
        ]
        lineas.append(" | ".join(partes))
    return "\n".join(lineas)


def _fmt_valor_md(col: str, val) -> str:
    """Formatea un valor para tabla markdown usando las reglas de moneda del config."""
    from .formatting import _es_valor_dinero, _formatear_moneda
    if val is None:
        return "—"
    if not isinstance(val, (int, float, Decimal)):
        return str(val)
    if _es_valor_dinero(col):
        return _formatear_moneda(float(val))
    # Número entero sin separador de miles (años, conteos, IDs)
    f = float(val)
    if f == int(f):
        return str(int(f))
    return f"{f:.2f}"


def formatear_plan_python(resultados: list[dict]) -> str:
    """Formatea resultados de plan multi-paso como tablas markdown sin LLM."""
    if not resultados:
        return "No hay datos disponibles en la base de datos para responder esta consulta."

    secciones = []
    for r in resultados:
        if not r.get("ok") or not r.get("datos"):
            continue
        datos     = r["datos"]
        proposito = r["proposito"]

        # Encabezado de sección
        secciones.append(f"**{proposito}**")

        # Cabecera de tabla
        cols = list(datos[0].keys())
        header    = "| " + " | ".join(cols) + " |"
        separator = "| " + " | ".join("---" for _ in cols) + " |"
        filas_md  = [header, separator]
        for fila in datos:
            celdas = [_fmt_valor_md(c, fila[c]) for c in cols]
            filas_md.append("| " + " | ".join(celdas) + " |")

        secciones.append("\n".join(filas_md))

    if not secciones:
        return "No hay datos disponibles en la base de datos para responder esta consulta."

    return "\n\n".join(secciones)


def _calcular_resumen_numerico(resultados: list[dict]) -> str:
    income_kw  = set(config.CONFIG.get("income_keywords",  []))
    expense_kw = set(config.CONFIG.get("expense_keywords", []))

    total_ingresos = 0.0
    total_gastos   = 0.0

    for r in resultados:
        if not r.get("ok") or not r.get("datos"):
            continue
        proposito = r["proposito"].lower()
        es_gasto  = any(p in proposito for p in expense_kw)
        for fila in r["datos"]:
            for col, val in fila.items():
                if not isinstance(val, (int, float, Decimal)):
                    continue
                col_lower = col.lower()
                val_f     = float(val)
                if es_gasto or any(p in col_lower for p in expense_kw):
                    total_gastos += val_f
                elif any(p in col_lower for p in income_kw):
                    total_ingresos += val_f

    if total_ingresos == 0 and total_gastos == 0:
        return ""

    gop    = total_ingresos - total_gastos
    estado = "GANANCIA" if gop >= 0 else "PÉRDIDA"
    return "\n".join([
        "=== RESUMEN CALCULADO POR EL SISTEMA (úsalos exactamente) ===",
        f"Total ingresos: {total_ingresos:,.2f}",
        f"Total gastos:   {total_gastos:,.2f}",
        f"GOP (resultado): {gop:,.2f}  → {estado}",
        "=============================================================",
    ])


async def sintetizar_local(pregunta: str, resultados: list[dict]) -> str:
    partes = []
    for r in resultados:
        if r["ok"] and r["datos"]:
            partes.append(f"[{r['proposito']}]\n{_formatear_tabla(r['datos'])}")

    # Si no hay datos reales, no llamar al LLM — evita alucinaciones
    if not partes:
        return "No hay datos disponibles en la base de datos para responder esta consulta."

    contexto          = "\n\n".join(partes)
    resumen_calculado = _calcular_resumen_numerico(resultados)
    biz_name          = config.biz("name", "negocio")

    prompt = f"""Pregunta del usuario: {pregunta}

{resumen_calculado}

Datos reales de la base de datos (números en formato anglosajón: punto decimal, coma miles):
{contexto}

INSTRUCCIONES ESTRICTAS:
- Reporta ÚNICAMENTE los números que aparecen en los datos de arriba.
- NO inventes, NO estimes, NO uses conocimiento propio.
- Si un dato no aparece arriba, NO lo menciones.
- El RESUMEN CALCULADO es la fuente de verdad para totales.
- {config.currency_hint()}
- Responde en español con markdown. No menciones SQL ni estructura interna."""

    system = (
        f"Eres un asistente de análisis de {biz_name}. "
        "Reportas ÚNICAMENTE los datos que recibes. "
        "Si no tienes datos, lo dices claramente. NUNCA inventas números."
    )
    return await llamar_ollama(prompt, system)


# ─── Generación de SQL simple ────────────────────────────────

async def generar_sql(pregunta: str, rol: str) -> tuple[str, str]:
    """Retorna (sql, modelo_usado) donde modelo_usado es 'claude' u 'ollama'."""
    schema   = config.schema_for(rol)
    biz_name = config.biz("name", "negocio")
    aliases  = config.aliases_text()
    kpis     = config.kpis_text()

    system = f"""Eres un experto en SQL PostgreSQL especializado en análisis de {biz_name}. Traduce preguntas en español a consultas SELECT.

Reglas:
- Responde SOLO con el bloque SQL: ```sql ... ```
- Siempre agregar LIMIT 100
- ILIKE para búsquedas de texto, SIEMPRE con wildcards: ILIKE '%valor%'
{aliases}
{kpis}
- CRÍTICO — cuando combines agregaciones de tablas distintas, SIEMPRE usa CTEs o subqueries independientes, NUNCA un JOIN directo entre ellas (produce producto cartesiano). Ejemplo:
  WITH ingresos AS (SELECT SUM(monto) AS total FROM pagos WHERE estado='pagado'),
       gastos_t AS (SELECT SUM(monto) AS total FROM gastos)
  SELECT i.total AS ingresos, g.total AS gastos, i.total - g.total AS resultado FROM ingresos i, gastos_t g
- CRÍTICO — si todos los datos necesarios están en UNA sola tabla, NO hagas JOIN con otras tablas
- Si la pregunta requiere datos que NO existen en el schema, responde EXACTAMENTE: SIN_DATOS: No tengo información de [dato faltante] en la base de datos para responder esa consulta.
- Nunca: INSERT, UPDATE, DELETE, DROP, SET
{SQL_GUIDELINES}"""

    prompt = f"Schema:\n{schema}\n\nPregunta: {pregunta}\n\nSQL:"

    if config.ANTHROPIC_KEY and config.ANTHROPIC_KEY != "sk-ant-tu-clave-aqui":
        try:
            client  = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_KEY)
            message = await client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            respuesta = message.content[0].text.strip()
            if respuesta.startswith("SIN_DATOS:"):
                raise HTTPException(status_code=422, detail=respuesta[len("SIN_DATOS:"):].strip())
            sql = extraer_sql(respuesta)
            logger.info(f"SQL generado (Claude): {sql}")
            validar_sql(sql)
            return sql, "claude"
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Claude API falló, usando Ollama: {e}")

    respuesta = await llamar_ollama(prompt, system)
    sql = extraer_sql(respuesta)
    logger.info(f"SQL generado (Ollama): {sql}")
    validar_sql(sql)
    return sql, "ollama"


async def ejecutar_sql(sql: str, rol: str, pregunta: str = "", intentos: int = 2) -> list[dict]:
    for intento in range(intentos):
        try:
            async with config.db_pool.acquire() as conn:
                filas = await conn.fetch(sql)
                return [dict(f) for f in filas]
        except asyncpg.PostgresError as e:
            error_msg = str(e)
            if intento < intentos - 1 and "does not exist" in error_msg:
                logger.warning(f"Corrigiendo SQL: {error_msg}")
                schema = config.schema_for(rol)
                prompt = (
                    f"SQL con error:\n{sql}\n\nError:\n{error_msg}\n\n"
                    f"Schema:\n{schema}\n\nDevuelve SOLO el SQL corregido: ```sql ... ```"
                )
                respuesta = await llamar_ollama(prompt)
                sql = extraer_sql(respuesta)
                validar_sql(sql)
            else:
                raise HTTPException(status_code=400, detail=f"Error en la consulta: {error_msg}")
