import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import config
from ..agent import ejecutar_plan, ejecutar_sql, formatear_plan_python, generar_plan, generar_sql
from ..audit import registrar_auditoria
from ..auth import get_role
from ..formatting import formatear_respuesta
from ..ratelimit import rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()


async def _audit(*args, **kwargs) -> None:
    try:
        await registrar_auditoria(*args, **kwargs)
    except Exception as e:
        logger.error(f"Error registrando auditoría: {e}")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "asistente-ia"
    messages: list[Message]
    stream: bool = False


class QueryRequest(BaseModel):
    pregunta: str


# ─────────────────────────────────────────────────────────────

@router.get("/api/health")
async def health():
    try:
        async with config.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "db": "conectada", "modelo": config.OLLAMA_MODEL}
    except Exception:
        return {"status": "degradado", "db": "desconectada"}


@router.post("/api/query")
async def query_simple(request: QueryRequest, rol: str = Depends(get_role), _rl: None = Depends(rate_limit)):
    t0        = time.monotonic()
    estado    = "ok"
    error_msg = None
    sql = modelo = ""
    datos: list[dict] = []
    respuesta = ""
    try:
        sql, modelo = await generar_sql(request.pregunta, rol)
        datos       = await ejecutar_sql(sql, rol, request.pregunta)
        respuesta   = formatear_respuesta(datos)
    except HTTPException as e:
        respuesta = e.detail
        estado, error_msg = "error", e.detail
        raise
    except Exception as e:
        logger.error(f"Error inesperado en /api/query: {e}")
        respuesta = "Ocurrió un error al procesar tu consulta."
        estado, error_msg = "error", str(e)
        raise HTTPException(status_code=500, detail=respuesta)
    finally:
        duracion_ms = int((time.monotonic() - t0) * 1000)
        asyncio.create_task(_audit(
            rol, request.pregunta, sql, len(datos),
            duracion_ms, estado, "simple", modelo, error_msg,
        ))
    return {"respuesta": respuesta, "filas": len(datos), "datos": datos}


_MAX_STREAM_CHARS = 32_000  # ~8k tokens; evita streaming de respuestas gigantes


async def _stream_respuesta(chat_id: str, model: str, respuesta: str) -> AsyncGenerator[str, None]:
    words = respuesta[:_MAX_STREAM_CHARS].split(" ")
    for i, word in enumerate(words):
        chunk = {
            "id": chat_id, "object": "chat.completion.chunk", "model": model,
            "choices": [{"index": 0, "delta": {"content": word + (" " if i < len(words) - 1 else "")}, "finish_reason": None}],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
    done = {"id": chat_id, "object": "chat.completion.chunk", "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    yield f"data: {json.dumps(done)}\n\ndata: [DONE]\n\n"


@router.post("/api/chat/completions")
@router.post("/api/v1/chat/completions")
async def chat_completions(request: ChatRequest, rol: str = Depends(get_role), _rl: None = Depends(rate_limit)):
    if not request.messages:
        raise HTTPException(status_code=400, detail="No hay mensajes.")

    pregunta = next((m.content for m in reversed(request.messages) if m.role == "user"), None)
    if not pregunta:
        raise HTTPException(status_code=400, detail="No se encontró mensaje del usuario.")

    logger.info(f"[Pregunta] {pregunta!r}")

    # Peticiones internas de Open WebUI (generación de títulos, etc.)
    if pregunta.startswith("### Task:") or pregunta.startswith("### "):
        payload = {
            "id": "chatcmpl-internal", "object": "chat.completion", "model": request.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": '{"follow_ups": []}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }
        if request.stream:
            async def _noop():
                yield f"data: {json.dumps(payload)}\n\ndata: [DONE]\n\n"
            return StreamingResponse(_noop(), media_type="text/event-stream")
        return payload

    t0          = time.monotonic()
    sql_log     = ""
    tipo_flujo  = "simple"
    modelo_llm  = "desconocido"
    filas_total = 0
    estado      = "ok"
    error_msg   = None

    try:
        pasos = await generar_plan(pregunta, rol)
        if pasos:
            tipo_flujo  = "plan"
            modelo_llm  = "claude" if (config.ANTHROPIC_KEY and config.ANTHROPIC_KEY != "sk-ant-tu-clave-aqui") else "local"
            sql_log     = f"[plan:{len(pasos)} pasos]"
            logger.info(f"Ejecutando plan de {len(pasos)} pasos")
            resultados  = await ejecutar_plan(pasos, rol, pregunta)
            respuesta   = formatear_plan_python(resultados)
            filas_total = sum(len(r["datos"]) for r in resultados if r["ok"])
        else:
            historial       = [{"role": m.role, "content": m.content} for m in request.messages]
            sql, modelo_llm = await generar_sql(pregunta, rol, historial)
            sql_log         = sql
            datos           = await ejecutar_sql(sql, rol, pregunta)
            respuesta       = formatear_respuesta(datos)
            filas_total     = len(datos)

    except HTTPException as e:
        respuesta = e.detail
        estado, error_msg = "error", e.detail
    except Exception as e:
        logger.error(f"Error inesperado: {e}")
        respuesta = "Ocurrió un error al procesar tu consulta. Por favor intenta reformularla."
        estado, error_msg = "error", str(e)

    duracion_ms = int((time.monotonic() - t0) * 1000)
    asyncio.create_task(_audit(
        rol, pregunta, sql_log, filas_total,
        duracion_ms, estado, tipo_flujo, modelo_llm, error_msg,
    ))

    chat_id = f"chatcmpl-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    if request.stream:
        return StreamingResponse(
            _stream_respuesta(chat_id, request.model, respuesta),
            media_type="text/event-stream",
        )

    return {
        "id": chat_id, "object": "chat.completion", "model": request.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": respuesta}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


@router.get("/api/models")
@router.get("/api/v1/models")
async def list_models(_rol: str = Depends(get_role)):
    return {
        "object": "list",
        "data": [{"id": config.biz("model_id", "asistente-ia"), "object": "model", "owned_by": "local"}],
    }
