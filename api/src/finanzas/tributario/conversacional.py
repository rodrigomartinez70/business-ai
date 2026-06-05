"""
Motor Conversacional Tributario (horizontal) — Q&A en lenguaje natural.

Agnóstico al vertical: `responder_tributario(pregunta, historial, calcular_fn)`
arma el contexto con `calcular_fn(hasta)` (el orquestador tributario del vertical)
y responde 100% con Ollama (local) — los montos NUNCA salen a Claude. Si Ollama
no está disponible, degrada al resumen de contexto crudo.
"""

import logging
from datetime import date

from src import config

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Eres un copiloto tributario para pequeñas y medianas empresas en Chile. "
    "Respondes en español, conciso y claro.\n\n"
    "REGLAS ESTRICTAS:\n"
    "- Para CIFRAS usa SOLO el CONTEXTO TRIBUTARIO provisto (son los datos reales "
    "de la empresa). Si un número no está en el contexto, dilo; NO lo calcules ni "
    "lo inventes.\n"
    "- Para CONCEPTOS usa SOLO las DEFINICIONES de abajo. NUNCA expliques un "
    "concepto tributario desde tu conocimiento propio; si te preguntan algo que no "
    "está en estas definiciones ni en el contexto, dilo y sugiere consultarlo con "
    "el contador.\n"
    "- No reemplazas al contador; ante temas complejos sugieres validarlo con él.\n\n"
    "DEFINICIONES CORRECTAS (Chile):\n"
    "- IVA (Impuesto al Valor Agregado): impuesto del 19%. El IVA débito es el "
    "recargado en las VENTAS del período; el IVA crédito es el soportado en las "
    "COMPRAS/gastos. Se paga la diferencia (débito menos crédito).\n"
    "- Remanente de crédito fiscal: IVA crédito no usado que queda a favor de la "
    "empresa para descontar en períodos siguientes.\n"
    "- F29: formulario MENSUAL donde se declara y paga el IVA y el PPM. Vence el "
    "día 20 del mes siguiente al período declarado.\n"
    "- PPM (Pago Provisional Mensual): anticipo mensual OBLIGATORIO del IMPUESTO A "
    "LA RENTA, calculado como un porcentaje sobre los ingresos brutos del mes. "
    "NO es una cotización previsional ni tiene relación con pensiones.\n"
    "- Retención de honorarios: impuesto retenido sobre las boletas de honorarios "
    "(servicios de personas naturales) que la empresa entera al SII.\n"
    "- UF (Unidad de Fomento): unidad de cuenta reajustable según la inflación, "
    "usada como referencia de valores.\n"
    "- Declaraciones Juradas (DJ): formularios informativos ANUALES que se "
    "presentan al SII (ej. DJ1879, DJ1887)."
)


def _resumen_contexto(data: dict) -> str:
    iva = data.get("agente_iva", {})
    cum = data.get("agente_cumplimiento", {})
    rie = data.get("agente_riesgo", {})
    acum = iva.get("acumulado_mes", {})
    f29  = iva.get("f29", {})

    # Una cifra por línea: un modelo local pequeño extrae los montos de forma más
    # fiable que en una línea densa con varios valores separados por ';'.
    lineas = ["CONTEXTO TRIBUTARIO (datos reales de la empresa):"]
    lineas.append(f"- IVA débito del mes: ${acum.get('iva_debito_acum', 0):,.0f}")
    lineas.append(f"- IVA crédito del mes: ${acum.get('iva_credito_acum', 0):,.0f} "
                  f"(fuente {acum.get('iva_credito_fuente', 'n/a')})")
    lineas.append(f"- F29 período {f29.get('periodo', '')}:")
    lineas.append(f"  - Remanente mes anterior: ${f29.get('remanente_anterior', 0):,.0f}")
    lineas.append(f"  - IVA a pagar: ${f29.get('iva_a_pagar', 0):,.0f}")
    lineas.append(f"  - PPM: ${f29.get('ppm', 0):,.0f}")
    lineas.append(f"  - Retención de honorarios: ${f29.get('retencion_honorarios', 0):,.0f}")
    lineas.append(f"  - TOTAL F29 a pagar: ${f29.get('total_a_pagar', 0):,.0f}")
    lineas.append(f"  - Vence: {f29.get('vencimiento', '')} "
                  f"(en {f29.get('dias_para_vencimiento', 0)} días)")
    if iva.get("uf_referencia"):
        lineas.append(f"- UF de referencia: ${iva['uf_referencia']:,.2f}")

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


async def responder_tributario(pregunta: str, historial: list[dict] | None, calcular_fn) -> str:
    """Q&A tributario. `calcular_fn(hasta)` = orquestador tributario del vertical."""
    try:
        data = await calcular_fn(date.today())
        contexto = _resumen_contexto(data)
    except Exception as e:
        logger.warning(f"No se pudo construir contexto tributario: {e}")
        contexto = "CONTEXTO TRIBUTARIO: no disponible en este momento."

    prompt = f"{contexto}\n\nPregunta del usuario: {pregunta}"

    # Copiloto financiero 100% local: el contexto tributario (montos F29, IVA, etc.)
    # NUNCA sale a Claude. Si Ollama no responde, se degrada al contexto crudo.
    respuesta = await _llamar_ollama(prompt, _SYSTEM)
    if respuesta:
        return respuesta

    return ("No tengo el asistente de lenguaje natural disponible ahora mismo, "
            "pero este es tu estado tributario actual:\n\n" + contexto)
