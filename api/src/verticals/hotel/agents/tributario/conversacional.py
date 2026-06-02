"""
Agente Conversacional — Q&A tributario en lenguaje natural.

Responde preguntas del usuario sobre su situación tributaria usando como
contexto el resultado de los agentes IVA, Cumplimiento y Riesgo, y un LLM
(Claude, con fallback a Ollama). Se expone como un "modelo" en Open WebUI.

No reemplaza al contador: explica, orienta y recomienda.
"""

import logging
from datetime import date

from src import config

logger = logging.getLogger(__name__)

_MAX_TOKENS = 700

_SYSTEM = (
    "Eres un copiloto tributario para pequeñas y medianas empresas en Chile. "
    "Explicas conceptos tributarios (IVA, F29, PPM, declaraciones juradas, UF) "
    "en lenguaje simple y das recomendaciones accionables. Usas SIEMPRE el "
    "contexto tributario provisto (son los datos reales de la empresa). "
    "No inventas cifras: si algo no está en el contexto, dilo. No reemplazas al "
    "contador; ante temas complejos sugieres validarlo con él. Respondes en "
    "español, conciso y claro."
)


def _resumen_contexto(data: dict) -> str:
    """Convierte el resultado de los agentes en un contexto compacto para el LLM."""
    iva = data.get("agente_iva", {})
    cum = data.get("agente_cumplimiento", {})
    rie = data.get("agente_riesgo", {})
    acum = iva.get("acumulado_mes", {})
    f29  = iva.get("f29", {})

    lineas = ["CONTEXTO TRIBUTARIO (datos reales de la empresa):"]
    lineas.append(
        f"- IVA del mes: débito ${acum.get('iva_debito_acum', 0):,.0f}, "
        f"crédito ${acum.get('iva_credito_acum', 0):,.0f}, "
        f"saldo ${acum.get('saldo_iva', 0):,.0f} "
        f"({acum.get('saldo_iva_uf', 0):.1f} UF), estado {acum.get('estado', 'n/a')}."
    )
    lineas.append(
        f"- F29 período {f29.get('periodo', '')}: a pagar ${f29.get('monto_estimado', 0):,.0f}, "
        f"vence {f29.get('vencimiento', '')} (en {f29.get('dias_para_vencimiento', 0)} días)."
    )
    if iva.get("uf_referencia"):
        lineas.append(f"- UF de referencia: ${iva['uf_referencia']:,.2f}.")

    venc = cum.get("proximos_vencimientos", [])
    if venc:
        items = "; ".join(f"{v['nombre']} el {v['fecha']} (en {v['dias_restantes']}d)"
                          for v in venc[:6])
        lineas.append(f"- Próximos vencimientos: {items}.")

    lineas.append(f"- Riesgo de fiscalización: {rie.get('score_riesgo', 'n/a')}.")
    for i in rie.get("inconsistencias", []):
        lineas.append(f"- Inconsistencia: {i.get('titulo', '')} — {i.get('descripcion', '')}")
    for a in rie.get("alertas", []):
        lineas.append(f"- Alerta ({a.get('nivel', '')}): {a.get('titulo', '')} — {a.get('descripcion', '')}")

    return "\n".join(lineas)


async def _llamar_ollama(prompt: str, system: str) -> str | None:
    import httpx
    payload = {
        "model": config.OLLAMA_MODEL, "prompt": prompt, "system": system,
        "stream": False, "options": {"temperature": 0.3, "num_predict": 600},
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{config.OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as e:
        logger.warning(f"Ollama tributario falló: {e}")
        return None


async def responder_tributario(pregunta: str, historial: list[dict] | None = None) -> str:
    """Responde una pregunta tributaria en lenguaje natural con contexto real."""
    from . import calcular_tributario_semanal  # lazy: evita ciclo de import

    try:
        data = await calcular_tributario_semanal(date.today())
        contexto = _resumen_contexto(data)
    except Exception as e:
        logger.warning(f"No se pudo construir contexto tributario: {e}")
        contexto = "CONTEXTO TRIBUTARIO: no disponible en este momento."

    prompt = f"{contexto}\n\nPregunta del usuario: {pregunta}"

    # Claude primero
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

    # Fallback Ollama
    respuesta = await _llamar_ollama(prompt, _SYSTEM)
    if respuesta:
        return respuesta

    # Sin LLM disponible: devolver el contexto como respuesta mínima útil
    return (
        "No tengo el asistente de lenguaje natural disponible ahora mismo, "
        "pero este es tu estado tributario actual:\n\n" + contexto
    )
