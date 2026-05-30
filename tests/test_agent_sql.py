"""
Tests del motor de generación y validación de SQL.

Estrategia:
  - Funciones puras (extraer_sql, validar_sql, wildcards): sin mocks.
  - Funciones con LLM (generar_sql, generar_plan): mock de anthropic y llamar_ollama.
    No se realizan llamadas reales a Claude ni a Ollama.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from src.agent import (
    _agregar_wildcards_ilike,
    extraer_sql,
    generar_plan,
    generar_sql,
    validar_sql,
)


# ── extraer_sql ───────────────────────────────────────────────

def test_extraer_sql_de_bloque_markdown():
    texto = "Aquí el SQL:\n```sql\nSELECT * FROM reservas LIMIT 10\n```"
    assert extraer_sql(texto).upper().startswith("SELECT")


def test_extraer_sql_sin_markdown():
    texto = "SELECT id, nombre FROM huespedes LIMIT 5"
    assert extraer_sql(texto).upper().startswith("SELECT")


def test_extraer_sql_elimina_comentarios_inline():
    texto = "```sql\nSELECT * FROM reservas -- comentario\nLIMIT 10\n```"
    assert "--" not in extraer_sql(texto)


def test_extraer_sql_elimina_punto_y_coma_final():
    assert not extraer_sql("SELECT 1;").endswith(";")


def test_extraer_sql_bloque_sin_lenguaje():
    texto = "```\nSELECT 1\n```"
    assert "SELECT" in extraer_sql(texto).upper()


# ── _agregar_wildcards_ilike ──────────────────────────────────

def test_wildcards_agrega_porcentaje():
    sql = "SELECT * FROM reservas WHERE estado ILIKE 'confirmada'"
    assert "ILIKE '%confirmada%'" in _agregar_wildcards_ilike(sql)


def test_wildcards_no_duplica_porcentaje_existente():
    sql = "SELECT * FROM reservas WHERE estado ILIKE '%confirmada%'"
    resultado = _agregar_wildcards_ilike(sql)
    assert resultado.count("%confirmada%") == 1


def test_wildcards_agrega_solo_prefijo_si_ya_tiene_sufijo():
    sql = "SELECT * FROM reservas WHERE estado ILIKE 'confirmada%'"
    assert "ILIKE '%confirmada%'" in _agregar_wildcards_ilike(sql)


# ── validar_sql ───────────────────────────────────────────────

def test_validar_sql_select_ok():
    validar_sql("SELECT * FROM reservas LIMIT 10")


def test_validar_sql_with_cte_ok():
    validar_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")


@pytest.mark.parametrize("sql", [
    "INSERT INTO reservas VALUES (1)",
    "UPDATE reservas SET estado='cancelada'",
    "DELETE FROM reservas",
    "DROP TABLE reservas",
    "TRUNCATE reservas",
    "ALTER TABLE reservas ADD COLUMN foo TEXT",
])
def test_validar_sql_bloquea_mutaciones(sql):
    with pytest.raises(HTTPException) as exc:
        validar_sql(sql)
    assert exc.value.status_code == 400


def test_validar_sql_rechaza_no_select():
    with pytest.raises(HTTPException) as exc:
        validar_sql("EXPLAIN SELECT 1")
    assert exc.value.status_code == 400


# ── generar_sql ───────────────────────────────────────────────

def _mock_claude_message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [MagicMock(text=text)]
    msg.usage = MagicMock(cache_read_input_tokens=0, cache_creation_input_tokens=100)
    return msg


@pytest.mark.asyncio
async def test_generar_sql_usa_claude_cuando_disponible():
    sql_esperado = "SELECT COUNT(*) FROM reservas LIMIT 100"
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            return_value=_mock_claude_message(f"```sql\n{sql_esperado}\n```")
        )
        sql, modelo = await generar_sql("¿cuántas reservas hay?", "gerente")

    assert modelo == "claude"
    assert "SELECT" in sql.upper()
    assert "reservas" in sql.lower()


@pytest.mark.asyncio
async def test_generar_sql_fallback_a_ollama_si_claude_falla():
    sql_esperado = "SELECT COUNT(*) FROM reservas LIMIT 100"
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls, \
         patch("src.agent.llamar_ollama", new_callable=AsyncMock) as mock_ollama:
        mock_cls.return_value.messages.create = AsyncMock(side_effect=Exception("timeout"))
        mock_ollama.return_value = f"```sql\n{sql_esperado}\n```"
        sql, modelo = await generar_sql("¿cuántas reservas hay?", "gerente")

    assert modelo == "ollama"
    assert "SELECT" in sql.upper()


@pytest.mark.asyncio
async def test_generar_sql_sin_anthropic_key_usa_ollama():
    sql_esperado = "SELECT COUNT(*) FROM reservas LIMIT 100"
    with patch("src.agent.config.ANTHROPIC_KEY", ""), \
         patch("src.agent.llamar_ollama", new_callable=AsyncMock) as mock_ollama:
        mock_ollama.return_value = f"```sql\n{sql_esperado}\n```"
        sql, modelo = await generar_sql("¿cuántas reservas hay?", "gerente")

    assert modelo == "ollama"


@pytest.mark.asyncio
async def test_generar_sql_lanza_422_para_sin_datos():
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            return_value=_mock_claude_message("SIN_DATOS: No tengo información de inventario.")
        )
        with pytest.raises(HTTPException) as exc:
            await generar_sql("¿cuántos unicornios hay?", "gerente")

    assert exc.value.status_code == 422
    assert "inventario" in exc.value.detail


# ── generar_plan ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generar_plan_retorna_none_para_pregunta_simple():
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            return_value=_mock_claude_message('{"pasos": null}')
        )
        resultado = await generar_plan("¿cuántas reservas hay este mes?", "gerente")

    assert resultado is None


@pytest.mark.asyncio
async def test_generar_plan_retorna_pasos_validos():
    plan = (
        '{"pasos": ['
        '{"id": 1, "proposito": "ingresos", "sql": "SELECT SUM(monto) FROM pagos LIMIT 100"},'
        '{"id": 2, "proposito": "gastos", "sql": "SELECT SUM(monto) FROM gastos LIMIT 100"}'
        ']}'
    )
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            return_value=_mock_claude_message(plan)
        )
        pasos = await generar_plan("¿cuál es el resultado operativo este mes?", "gerente")

    assert pasos is not None
    assert len(pasos) == 2
    assert all("proposito" in p and "sql" in p for p in pasos)


@pytest.mark.asyncio
async def test_generar_plan_retorna_none_sin_anthropic_key():
    with patch("src.agent.config.ANTHROPIC_KEY", ""):
        resultado = await generar_plan("¿cuál fue el mejor mes?", "gerente")
    assert resultado is None


@pytest.mark.asyncio
async def test_generar_plan_rechaza_sql_con_mutaciones():
    plan = '{"pasos": [{"id": 1, "proposito": "hack", "sql": "DELETE FROM reservas"}]}'
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            return_value=_mock_claude_message(plan)
        )
        with pytest.raises(HTTPException) as exc:
            await generar_plan("borra todo", "gerente")

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_generar_plan_lanza_422_para_sin_datos():
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            return_value=_mock_claude_message('{"pasos": null, "sin_datos": "No hay datos de stock."}')
        )
        with pytest.raises(HTTPException) as exc:
            await generar_plan("¿cuánto stock queda?", "gerente")

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_generar_plan_trunca_a_4_pasos():
    pasos_json = ", ".join(
        f'{{"id": {i}, "proposito": "paso {i}", "sql": "SELECT {i} LIMIT 100"}}'
        for i in range(1, 7)
    )
    plan = f'{{"pasos": [{pasos_json}]}}'
    with patch("src.agent.config.ANTHROPIC_KEY", "sk-ant-real-key"), \
         patch("src.agent.anthropic.AsyncAnthropic") as mock_cls:
        mock_cls.return_value.messages.create = AsyncMock(
            return_value=_mock_claude_message(plan)
        )
        pasos = await generar_plan("pregunta compleja con muchos pasos", "gerente")

    assert pasos is not None
    assert len(pasos) <= 4
