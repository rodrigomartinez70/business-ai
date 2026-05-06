"""
Bot de Discord — Plataforma IA de Análisis de Negocio

Comandos disponibles (sin LLM intermedio — cada uno llama al endpoint correcto):
  !kpis [dias]     — KPIs del período e indicadores de alerta
  !reporte [dias]  — Reporte ejecutivo del negocio
  !uso             — Uso e interacciones del agente (últimos 30 días)
  !ayuda           — Lista de comandos disponibles
  !reset           — Limpia el historial de conversación

Cualquier mensaje sin ! se procesa como consulta en lenguaje natural.
"""

import logging
import os

import discord
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_URL       = os.getenv("API_URL", "http://negocio_api:8000")
API_KEY       = os.getenv("DISCORD_API_KEY", "")
CHANNEL_ID    = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
MAX_HISTORY   = int(os.getenv("DISCORD_MAX_HISTORY", "10"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
MODEL_ID      = os.getenv("DISCORD_MODEL_ID", "asistente-ia")

# Historial de conversación por canal (para consultas en lenguaje natural)
histories: dict[int, list[dict]] = {}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

AYUDA = """**Comandos disponibles:**

`!kpis` — KPIs del período (últimos 7 días) e indicadores de alerta
`!kpis 14` — KPIs de los últimos N días
`!reporte` — Reporte ejecutivo de la última semana
`!reporte 30` — Reporte ejecutivo de los últimos N días
`!uso` — Uso del agente e interacciones (últimos 30 días)
`!cargar gastos` — Importa un CSV adjunto a la tabla indicada (modo validar)
`!cargar gastos insertar` — Importa y confirma la inserción
`!reset` — Limpia el historial de conversación
`!ayuda` — Muestra este mensaje

Sin `!` → consulta en lenguaje natural al agente text-to-SQL."""


def _split_message(text: str, limit: int = 1990) -> list[str]:
    """Divide texto largo en chunks respetando el límite de Discord."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunk = text[:limit]
        last_newline = chunk.rfind("\n")
        if last_newline > limit // 2:
            chunk = chunk[:last_newline]
        chunks.append(chunk)
        text = text[len(chunk):]
    return chunks


async def _get_markdown(url: str) -> str:
    """Llama a un endpoint GET que devuelve texto markdown."""
    async with httpx.AsyncClient(timeout=120) as http:
        response = await http.get(
            url,
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        response.raise_for_status()
        return response.text


async def _chat(messages: list[dict]) -> str:
    """Llama al endpoint de chat completions y devuelve la respuesta."""
    async with httpx.AsyncClient(timeout=120) as http:
        response = await http.post(
            f"{API_URL}/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": MODEL_ID, "messages": messages, "stream": False},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def _parse_dias(parts: list[str], default: int = 7) -> int:
    """Extrae el argumento numérico de un comando (ej. ['!kpis', '14'] → 14)."""
    if len(parts) > 1 and parts[1].isdigit():
        return max(1, min(365, int(parts[1])))
    return default


@client.event
async def on_ready():
    logger.info(f"Bot conectado como {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if message.channel.id != CHANNEL_ID:
        return

    content = message.content.strip()
    parts   = content.split()
    cmd     = parts[0].lower() if parts else ""

    # ── Comandos de control ──────────────────────────────────
    if cmd in ("!reset", "!limpiar", "!nuevo"):
        histories.pop(message.channel.id, None)
        await message.reply("Historial limpiado.")
        return

    if cmd == "!ayuda":
        await message.channel.send(AYUDA)
        return

    # ── Comandos de agentes (sin LLM) ────────────────────────
    async with message.channel.typing():
        try:
            if cmd == "!kpis":
                dias = _parse_dias(parts)
                texto = await _get_markdown(
                    f"{API_URL}/api/agents/alertas?periodo_dias={dias}&formato=markdown"
                )

            elif cmd == "!reporte":
                dias = _parse_dias(parts)
                texto = await _get_markdown(
                    f"{API_URL}/api/report/weekly?dias={dias}&formato=markdown"
                )

            elif cmd == "!uso":
                texto = await _get_markdown(
                    f"{API_URL}/api/report/usage?formato=markdown"
                )

            elif cmd == "!cargar":
                if len(parts) < 2:
                    await message.reply("Uso: `!cargar {tabla} [insertar]`\nEjemplo: `!cargar gastos` + adjuntar CSV")
                    return
                tabla = parts[1].lower()
                modo  = "insertar" if len(parts) > 2 and parts[2].lower() == "insertar" else "validar"
                if not message.attachments:
                    await message.reply("Adjunta un archivo CSV al mensaje.\nEjemplo: `!cargar gastos` + 📎 archivo.csv")
                    return
                adjunto = message.attachments[0]
                if not adjunto.filename.lower().endswith(".csv"):
                    await message.reply("El archivo debe tener extensión `.csv`.")
                    return
                csv_bytes = await adjunto.read()
                async with httpx.AsyncClient(timeout=60) as http:
                    resp = await http.post(
                        f"{API_URL}/api/ingest/{tabla}?modo={modo}",
                        headers={"Authorization": f"Bearer {API_KEY}"},
                        files={"archivo": (adjunto.filename, csv_bytes, "text/csv")},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                if modo == "validar":
                    ignoradas = f"\n⚠️ Columnas ignoradas: `{', '.join(data['columnas_ignoradas'])}`" if data["columnas_ignoradas"] else ""
                    texto = (
                        f"**Validación — `{tabla}`**\n"
                        f"✅ {data['filas_a_insertar']} filas listas para insertar\n"
                        f"Columnas: `{', '.join(data['columnas_validas'])}`{ignoradas}\n\n"
                        f"Para confirmar: `!cargar {tabla} insertar` + mismo archivo"
                    )
                else:
                    ignoradas = f"\n⚠️ Columnas ignoradas: `{', '.join(data['columnas_ignoradas'])}`" if data["columnas_ignoradas"] else ""
                    texto = f"**Importación — `{tabla}`**\n✅ {data['filas_insertadas']} filas insertadas.{ignoradas}"

            elif cmd.startswith("!"):
                # Comando desconocido
                await message.reply(f"Comando no reconocido: `{cmd}`\nEscribe `!ayuda` para ver los comandos disponibles.")
                return

            else:
                # Consulta en lenguaje natural → historial + chat completions
                channel_id = message.channel.id
                if channel_id not in histories:
                    histories[channel_id] = []

                histories[channel_id].append({"role": "user", "content": content})
                if len(histories[channel_id]) > MAX_HISTORY:
                    histories[channel_id] = histories[channel_id][-MAX_HISTORY:]

                texto = await _chat(histories[channel_id])
                histories[channel_id].append({"role": "assistant", "content": texto})

        except httpx.HTTPStatusError as e:
            logger.error(f"Error API {e.response.status_code}: {e.response.text}")
            await message.reply("No pude obtener respuesta del agente. Intenta de nuevo.")
            return
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
            await message.reply("Ocurrió un error al procesar tu consulta.")
            return

    for chunk in _split_message(texto):
        await message.channel.send(chunk)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN no está configurado.")
    if not API_KEY:
        raise RuntimeError("DISCORD_API_KEY no está configurado.")
    if CHANNEL_ID == 0:
        raise RuntimeError("DISCORD_CHANNEL_ID no está configurado.")
    client.run(DISCORD_TOKEN)
