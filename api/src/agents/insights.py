"""
Motor genérico de insights accionables con IA.

Los prompts y resumidores específicos del negocio viven en
src/verticals/<vertical>/insights_prompts.py y se cargan según
BUSINESS_VERTICAL del entorno. Lo que sale al exterior son únicamente
recomendaciones en texto, nunca los números crudos del negocio.
"""

import importlib
import logging
from typing import Optional

from .. import config

logger = logging.getLogger(__name__)

_MAX_TOKENS = 512


def _cargar_prompts() -> tuple[str, dict, dict]:
    """Carga SYSTEM, PROMPTS y RESUMIDORES del vertical activo."""
    from ..tenant import get_tenant_or_none
    ctx = get_tenant_or_none()
    vertical = ctx.vertical if ctx is not None else config.BUSINESS_VERTICAL
    module_path = f"src.verticals.{vertical}.insights_prompts"
    try:
        mod = importlib.import_module(module_path)
        return mod.SYSTEM, mod.PROMPTS, mod.RESUMIDORES
    except (ImportError, AttributeError) as e:
        logger.error(f"No se pudo cargar insights_prompts para vertical '{vertical}': {e}")
        return "", {}, {}


async def _llamar_ollama_insights(prompt: str, system: str) -> Optional[str]:
    import httpx
    payload = {
        "model":  config.OLLAMA_MODEL,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 400},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{config.OLLAMA_URL}/api/generate", json=payload
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as e:
        logger.warning(f"Ollama insights falló: {e}")
        return None


async def generar_insights(tipo: str, data: dict) -> list[str]:
    """
    Genera insights accionables para el agente indicado.

    Los datos se procesan internamente — solo el texto de recomendación
    sale como respuesta, nunca los números crudos del negocio.

    Retorna lista de bullets (strings). Lista vacía si falla ambos LLMs.
    """
    system, prompts, resumidores = _cargar_prompts()

    resumidor = resumidores.get(tipo)
    template  = prompts.get(tipo)
    if not resumidor or not template:
        logger.warning(f"Tipo de agente desconocido para insights en vertical '{vertical}': {tipo}")
        return []

    try:
        resumen = resumidor(data)
    except Exception as e:
        logger.warning(f"Error al resumir datos para insights ({tipo}): {e}")
        return []

    biz_name = config.biz("name", "negocio")
    prompt   = template.format(resumen=resumen).strip()
    prompt  += f"\n\nNegocio: {biz_name}. Respondé en español con bullets (•)."

    respuesta = None

    if config.claude_disponible():
        try:
            client  = config.get_anthropic_client()
            message = await client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            respuesta = message.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Claude insights falló ({tipo}), usando Ollama: {e}")

    if not respuesta:
        respuesta = await _llamar_ollama_insights(prompt, system)

    if not respuesta:
        return []

    bullets = []
    for line in respuesta.splitlines():
        line = line.strip()
        if not line:
            continue
        for prefix in ("• ", "- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        if len(line) > 10:
            bullets.append(line)

    return bullets[:3]
