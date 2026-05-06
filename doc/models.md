# Guía de modelos LLM

El sistema usa dos modelos con roles distintos y complementarios.

---

## Cómo se usan los modelos

| Modelo | Variable | Rol en el sistema | Datos que ve |
| --- | --- | --- | --- |
| Claude | `CLAUDE_MODEL` | Planificación multi-paso y generación de SQL | Solo el schema (nunca datos reales) |
| Ollama | `OLLAMA_MODEL` | Síntesis de resultados en lenguaje natural | Los datos retornados por la DB |

**Por qué esta separación:** Claude es el modelo más capaz para razonar sobre el schema y generar SQL correcto. Ollama corre localmente en el servidor, lo que garantiza que los datos del negocio nunca salen de la VM al sintetizar la respuesta final.

Si `ANTHROPIC_API_KEY` no está configurada, el sistema usa Ollama para todo (SQL + síntesis). La calidad del SQL baja pero el sistema sigue operativo.

---

## Claude (`CLAUDE_MODEL`)

### Dónde configurar

En `.env`:

```env
CLAUDE_MODEL=claude-haiku-4-5
ANTHROPIC_API_KEY=sk-ant-api03-...
```

### Modelos disponibles

| Modelo | Velocidad | Calidad SQL | Costo | Recomendado para |
| --- | --- | --- | --- | --- |
| `claude-haiku-4-5` | Muy rápida | Buena | Bajo | Producción con volumen alto |
| `claude-sonnet-4-6` | Media | Muy buena | Medio | Producción con queries complejas |
| `claude-opus-4-7` | Lenta | Excelente | Alto | Casos con schemas muy complejos |

**Recomendación general:** empezar con `claude-haiku-4-5`. Subir a `claude-sonnet-4-6` si el agente genera SQL incorrecto frecuentemente o el schema tiene muchas tablas y relaciones.

### Cómo cambiar el modelo

1. Editar `.env`:

```env
CLAUDE_MODEL=claude-sonnet-4-6
```

2. Reiniciar la API:

```bash
docker compose restart api
```

No requiere rebuild.

### Obtener la API key de Anthropic

1. Ir a [console.anthropic.com](https://console.anthropic.com)
2. Crear una cuenta o iniciar sesión
3. En el menú: **API Keys → Create Key**
4. Copiar la key (solo se muestra una vez) y pegarla en `.env` como `ANTHROPIC_API_KEY`

### Monitorear el uso y costos

Desde [console.anthropic.com](https://console.anthropic.com) → **Usage** se puede ver el consumo por día y por modelo. El endpoint `/api/report/usage` también muestra qué modelo se usó en cada consulta (`modelo_llm`).

---

## Ollama (`OLLAMA_MODEL`)

### Dónde configurar

En `.env`:

```env
OLLAMA_MODEL=llama3.2:3b
OLLAMA_URL=http://ollama:11434
```

### Modelos disponibles

| Modelo | RAM necesaria | Calidad | Velocidad | Recomendado para |
| --- | --- | --- | --- | --- |
| `llama3.2:3b` | 4 GB | Suficiente | Muy rápida | VMs con recursos limitados |
| `llama3.1:8b` | 8 GB | Buena | Rápida | Balance calidad/recursos |
| `llama3.3:70b` | 48 GB | Muy buena | Lenta | Servidores con GPU |
| `qwen2.5:7b` | 8 GB | Buena | Rápida | Alternativa a llama3.1 |
| `mistral:7b` | 8 GB | Buena | Rápida | Alternativa general |
| `gemma2:9b` | 10 GB | Buena | Media | Alternativa de Google |

> La RAM indicada es la necesaria para correr el modelo en CPU. Con GPU el requerimiento de RAM de sistema baja significativamente.

### Cómo cambiar el modelo

#### Paso 1 — Descargar el modelo en Ollama

Si Ollama corre como servicio externo (otra VM o contenedor compartido):

```bash
# Conectarse a la VM donde corre Ollama
ollama pull llama3.1:8b
```

Si Ollama corre en la misma VM pero sin estar definido en este `docker-compose.yml` (servicio compartido):

```bash
# Desde la VM
curl http://localhost:11434/api/pull -d '{"name": "llama3.1:8b"}'
```

#### Paso 2 — Actualizar la variable

En `.env`:

```env
OLLAMA_MODEL=llama3.1:8b
```

#### Paso 3 — Reiniciar la API

```bash
docker compose restart api
```

### Verificar que el modelo está disponible

```bash
# Listar modelos descargados en Ollama
curl http://IP_OLLAMA:11434/api/tags
```

Si el modelo no aparece en la lista, la API caerá al iniciar con un error en los logs. Descargar el modelo antes de cambiar la variable.

### Agregar Ollama al docker-compose (si no existe en la infraestructura)

Si la VM no tiene Ollama, agregarlo como servicio en `docker-compose.yml`:

```yaml
ollama:
  image: ollama/ollama
  container_name: ollama
  restart: unless-stopped
  volumes:
    - ollama_data:/root/.ollama
  # Descomentar si la VM tiene GPU NVIDIA:
  # deploy:
  #   resources:
  #     reservations:
  #       devices:
  #         - driver: nvidia
  #           count: 1
  #           capabilities: [gpu]
```

Y agregar el volumen en la sección `volumes`:

```yaml
volumes:
  ollama_data:
  # ... resto de volúmenes
```

Luego descargar el modelo la primera vez:

```bash
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.2:3b
```

---

## Escenarios comunes

### Producción con bajo volumen de consultas

```env
CLAUDE_MODEL=claude-sonnet-4-6
OLLAMA_MODEL=llama3.1:8b
```

Mejor calidad de SQL y síntesis, costo moderado.

### Producción con alto volumen

```env
CLAUDE_MODEL=claude-haiku-4-5
OLLAMA_MODEL=llama3.2:3b
```

Máxima velocidad y mínimo costo. Adecuado cuando las preguntas son repetitivas y el schema no es muy complejo.

### Sin conexión a internet (modo offline total)

```env
ANTHROPIC_API_KEY=   # vacío — el sistema usa Ollama para todo
OLLAMA_MODEL=llama3.1:8b
```

El agente usa Ollama tanto para generar SQL como para sintetizar. La calidad del SQL generado es menor pero el sistema no depende de ninguna API externa.

### Evaluación / desarrollo local

```env
CLAUDE_MODEL=claude-haiku-4-5
OLLAMA_MODEL=llama3.2:3b
```

El modelo más rápido y económico de cada proveedor para iterar rápido durante el desarrollo.

---

## Identificar qué modelo se usó en cada consulta

El endpoint `/api/report/usage` muestra el desglose de consultas por modelo:

```bash
curl -H "Authorization: Bearer TU_API_KEY" \
  "http://localhost:81/app/api/report/usage?formato=markdown"
```

La columna `modelo_llm` registra uno de estos valores:

| Valor | Significado |
| --- | --- |
| `claude` | Flujo simple — SQL generado por Claude |
| `ollama` | Flujo simple — Claude falló, SQL generado por Ollama |
| `claude+ollama` | Flujo multi-paso — Claude planificó, Ollama sintetizó |
