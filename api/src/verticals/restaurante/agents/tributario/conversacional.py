"""
Agente Conversacional Tributario — restaurante.

Reutiliza el system prompt, el formateador de contexto y el fallback Ollama del
vertical hotel (agnósticos), pero arma el contexto con los datos tributarios del
restaurante.
"""

import logging
from datetime import date

from src import config
from src.verticals.hotel.agents.tributario.conversacional import (
    _SYSTEM, _resumen_contexto, _llamar_ollama,
)

logger = logging.getLogger(__name__)
_MAX_TOKENS = 700


async def responder_tributario(pregunta: str, historial: list[dict] | None = None) -> str:
    from . import calcular_tributario_semanal  # lazy: evita ciclo de import

    try:
        data = await calcular_tributario_semanal(date.today())
        contexto = _resumen_contexto(data)
    except Exception as e:
        logger.warning(f"No se pudo construir contexto tributario: {e}")
        contexto = "CONTEXTO TRIBUTARIO: no disponible en este momento."

    prompt = f"{contexto}\n\nPregunta del usuario: {pregunta}"

    if config.claude_disponible():
        try:
            client = config.get_anthropic_client()
            msgs = []
            for m in (historial or [])[-6:]:
                if m.get("role") in ("user", "assistant") and m.get("content"):
                    msgs.append({"role": m["role"], "content": m["content"]})
            msgs.append({"role": "user", "content": prompt})
            message = await client.messages.create(
                model=config.CLAUDE_MODEL, max_tokens=_MAX_TOKENS,
                system=_SYSTEM, messages=msgs,
            )
            return message.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Claude tributario falló, usando Ollama: {e}")

    respuesta = await _llamar_ollama(prompt, _SYSTEM)
    if respuesta:
        return respuesta

    return ("No tengo el asistente de lenguaje natural disponible ahora mismo, "
            "pero este es tu estado tributario actual:\n\n" + contexto)
