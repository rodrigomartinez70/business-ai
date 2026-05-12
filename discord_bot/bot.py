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

import asyncio
import logging
import os
from contextlib import asynccontextmanager

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


async def _get_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=120) as http:
        response = await http.get(url, headers={"Authorization": f"Bearer {API_KEY}"})
        response.raise_for_status()
        return response.json()


async def _get_markdown(url: str) -> str:
    async with httpx.AsyncClient(timeout=120) as http:
        response = await http.get(url, headers={"Authorization": f"Bearer {API_KEY}"})
        response.raise_for_status()
        return response.text


async def _chat(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=120) as http:
        response = await http.post(
            f"{API_URL}/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={"model": MODEL_ID, "messages": messages, "stream": False},
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def _parse_dias(parts: list[str], default: int = 7) -> int:
    if len(parts) > 1 and parts[1].isdigit():
        return max(1, min(365, int(parts[1])))
    return default


def _fmt_kpi_valor(kpi: dict) -> str:
    valor = kpi.get("valor")
    if valor is None:
        return "—"
    unidad = kpi.get("unidad", "número")
    if unidad == "%":
        return f"{valor:.1f}%"
    if unidad == "moneda":
        return f"${valor:,.0f}".replace(",", ".")
    return f"{valor:,.0f}" if valor == int(valor) else f"{valor:.2f}"


def _fmt_kpi_estado(kpi: dict, alertas: list[dict]) -> str:
    if kpi.get("valor") is None:
        return "— sin datos"
    match = next((a for a in alertas if a["kpi"] == kpi["name"]), None)
    if not match:
        return "✅ OK"
    icono = "🚨" if match["nivel"] == "critico" else "⚠️"
    return f"{icono} {match['umbral']}"


def _build_kpis_embed(data: dict, dias: int) -> discord.Embed:
    estado = data.get("estado_general", "ok")
    biz    = data.get("business_name", "Negocio")

    color = discord.Color.green()
    icono = "✅"
    if estado == "alerta":
        color = discord.Color.gold()
        icono = "⚠️"
    elif estado == "critico":
        color = discord.Color.red()
        icono = "🚨"

    kpis    = data.get("kpis", [])
    alertas = data.get("alertas", [])

    embed = discord.Embed(
        title=f"{icono} KPIs — {biz} · Últimos {dias} días · {estado.upper()}",
        color=color,
    )

    lineas = []
    for kpi in kpis:
        valor      = _fmt_kpi_valor(kpi)
        estado_kpi = _fmt_kpi_estado(kpi, alertas)
        lineas.append(f"**{kpi['name']}:** {valor} · {estado_kpi}")

    embed.add_field(name="Indicadores", value="\n".join(lineas), inline=False)

    if alertas:
        alertas_txt = "\n".join(
            f"{'🚨' if a['nivel'] == 'critico' else '⚠️'} **{a['kpi']}**: {a['valor']} (umbral: {a['umbral']})"
            for a in alertas
        )
        embed.add_field(name="Alertas activas", value=alertas_txt, inline=False)

    return embed


def _build_uso_embed(data: dict) -> discord.Embed:
    periodo  = data.get("periodo", {})
    resumen  = data.get("resumen", {})
    por_rol  = data.get("por_rol", [])
    por_dia  = data.get("por_dia", [])

    tasa     = resumen.get("tasa_exito_pct", 0)
    color    = discord.Color.green() if tasa >= 95 else discord.Color.gold()

    embed = discord.Embed(
        title="📊 Uso del agente",
        description=f"Período: {periodo.get('inicio')} → {periodo.get('fin')}",
        color=color,
    )

    lat = resumen.get("duracion_promedio_ms")
    lat_txt = f"{lat:,.0f} ms" if lat else "—"

    embed.add_field(
        name="Resumen",
        value=(
            f"**Consultas:** {resumen.get('total_consultas', 0)}\n"
            f"**Exitosas:** {resumen.get('consultas_ok', 0)}\n"
            f"**Errores:** {resumen.get('consultas_error', 0)}\n"
            f"**Tasa éxito:** {tasa:.1f}%\n"
            f"**Latencia prom.:** {lat_txt}"
        ),
        inline=True,
    )

    if por_rol:
        rol_txt = "\n".join(
            f"**{r['rol']}:** {r['consultas']} consultas"
            for r in por_rol
        )
        embed.add_field(name="Por rol", value=rol_txt, inline=True)

    if por_dia:
        dias_recientes = por_dia[-5:]
        dia_txt = "\n".join(
            f"`{d['dia']}` — {d['consultas']} consultas"
            for d in dias_recientes
        )
        embed.add_field(name="Actividad reciente", value=dia_txt, inline=False)

    return embed


@client.event
async def on_ready():
    logger.info(f"Bot conectado como {client.user}")


@asynccontextmanager
async def _safe_typing(channel):
    # fire-and-forget: don't await so discord.py rate-limit retries never block the handler
    async def _pulse():
        try:
            await channel._state.http.send_typing(channel.id)
        except Exception:
            pass
    asyncio.ensure_future(_pulse())
    yield


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    allowed = {message.channel.id, getattr(message.channel, "parent_id", None)}
    if CHANNEL_ID not in allowed:
        return

    content = message.content.strip()
    parts   = content.split()
    cmd     = parts[0].lower() if parts else ""

    if cmd in ("!reset", "!limpiar", "!nuevo"):
        histories.pop(message.channel.id, None)
        await message.reply("Historial limpiado.")
        return

    if cmd == "!ayuda":
        await message.channel.send(AYUDA)
        return

    async with _safe_typing(message.channel):
        try:
            if cmd == "!kpis":
                dias = _parse_dias(parts)
                data  = await _get_json(f"{API_URL}/api/agents/alertas?periodo_dias={dias}")
                embed = _build_kpis_embed(data, dias)
                await message.channel.send(embed=embed)
                return

            elif cmd == "!uso":
                data  = await _get_json(f"{API_URL}/api/report/usage")
                embed = _build_uso_embed(data)
                await message.channel.send(embed=embed)
                return

            elif cmd == "!reporte":
                dias  = _parse_dias(parts)
                texto = await _get_markdown(f"{API_URL}/api/report/weekly?dias={dias}&formato=markdown")

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
                    texto = f"**Importación — `{tabla}`**\n✅ {data['filas_procesadas']} filas procesadas.{ignoradas}"

            elif cmd.startswith("!"):
                await message.reply(f"Comando no reconocido: `{cmd}`\nEscribe `!ayuda` para ver los comandos disponibles.")
                return

            else:
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
