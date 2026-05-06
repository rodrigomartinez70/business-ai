# Guía de conexión con Discord — Agente IA

## ¿Cómo funciona?

El bot de Discord es un puente entre tu canal de Discord y el mismo agente que opera detrás de la interfaz web. La consulta viaja así:

```
Mensaje en Discord → Bot → API (text-to-SQL) → PostgreSQL → Respuesta en Discord
```

El agente es idéntico: mismas capacidades, mismo modelo, mismos datos.

---

## Diferencias respecto a la interfaz web

| | Open WebUI (web) | Discord |
|---|---|---|
| Respuesta | Se escribe palabra a palabra (streaming) | Aparece completa de una vez |
| Historial | Guardado permanentemente por conversación | Se mantiene mientras el bot está activo; se pierde si se reinicia el contenedor |
| Límite de respuesta | Sin límite visible | Mensajes largos se dividen automáticamente |
| Acceso | Usuario + contraseña | Cualquiera con acceso al canal |
| Formato | Markdown renderizado | Markdown parcialmente renderizado |

---

## Configuración inicial (una sola vez)

### Paso 1 — Crear el bot en Discord

1. Entra a **https://discord.com/developers/applications**
2. Clic en **New Application** → ponle un nombre (ej: `Agente IA`)
3. En el menú izquierdo → **Bot**
4. Clic en **Reset Token** → copia el token (lo necesitas en el paso 3)
5. En la misma página, activa **Message Content Intent** (sin esto el bot no puede leer mensajes)

### Paso 2 — Invitar el bot a tu servidor

1. En el menú izquierdo → **OAuth2 → URL Generator**
2. En *Scopes* marca: `bot`
3. En *Bot Permissions* marca: `Read Messages/View Channels`, `Send Messages`, `Read Message History`
4. Copia la URL generada y ábrela en el navegador
5. Selecciona tu servidor y confirma

### Paso 3 — Obtener el ID del canal

1. En Discord → **Ajustes de usuario → Avanzado → activa Modo desarrollador**
2. Click derecho sobre el canal donde quieres que responda el bot
3. Clic en **Copiar ID del canal**

### Paso 4 — Configurar el `.env`

Abre el archivo `.env` del proyecto y completa:

```
DISCORD_TOKEN=tu_token_aqui
DISCORD_CHANNEL_ID=id_del_canal_aqui
```

### Paso 5 — Levantar el bot

```bash
docker compose build discord_bot && docker compose up -d discord_bot
```

Para verificar que arrancó correctamente:

```bash
docker compose logs discord_bot --tail=20
```

Deberías ver: `Bot conectado como Agente IA#XXXX`

---

## Cómo usar el bot

Una vez activo, simplemente escribe tu pregunta en el canal configurado como si fuera un chat normal. No hace falta ningún prefijo ni mencionar al bot.

**Ejemplos:**

```
¿Cuáles fueron los ingresos de marzo?
```
```
¿Qué registros están activos hoy?
```
```
Compara gastos vs ingresos del primer trimestre
```
```
¿Cuál es la categoría más rentable?
```

### Comandos especiales

| Comando | Función |
|---|---|
| `!reset` | Limpia el historial de la conversación actual |
| `!limpiar` | Igual que `!reset` |
| `!nuevo` | Igual que `!reset` |

### Contexto de conversación

El bot recuerda los últimos 10 mensajes del canal. Puedes hacer preguntas de seguimiento:

```
Usuario: ¿Cuáles fueron los ingresos de enero?
Bot: Los ingresos de enero fueron...

Usuario: ¿Y en febrero?        ← el bot entiende que sigue hablando de ingresos
Bot: En febrero los ingresos fueron...
```

Si cambias de tema o el contexto se vuelve confuso, usa `!reset` para empezar limpio.

---

## Seguridad

- El bot usa la API key de **gerente** por defecto, con acceso completo a todos los datos.
- Cualquier persona con acceso al canal puede hacer consultas.
- **Recomendación:** usa un canal privado visible solo para las personas autorizadas.

---

## Solución de problemas

**El bot no responde:**
```bash
docker compose logs discord_bot --tail=50
```

**Error "Message Content Intent":** vuelve al portal de desarrolladores de Discord y verifica que el intent esté activado.

**Respuestas cortadas:** es normal — el bot divide automáticamente las respuestas largas en varios mensajes consecutivos.

**Reiniciar el bot:**
```bash
docker compose restart discord_bot
```
