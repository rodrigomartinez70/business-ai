# Guía de configuración por proyecto

Para adaptar la plataforma a un nuevo negocio se modifican dos archivos: `.env` y `api/config.yaml`. No se toca código Python.

---

## Archivo `.env`

Contiene credenciales y parámetros de infraestructura. Nunca subir al repositorio (está en `.gitignore`).

### Base de datos

| Variable | Descripción | Ejemplo |
|---|---|---|
| `POSTGRES_USER` | Usuario administrador de PostgreSQL | `negocio_admin` |
| `POSTGRES_PASSWORD` | Contraseña del administrador | `password_seguro_aqui` |
| `POSTGRES_DB` | Nombre de la base de datos | `negocio_db` |
| `NEGOCIO_USER_PASSWORD` | Contraseña del usuario de aplicación (acceso restringido a SELECT) | `otro_password_seguro` |

> `POSTGRES_USER` tiene permisos totales sobre la DB. `negocio_user` (el que usa la API) solo tiene permisos SELECT, lo que evita que el agente modifique datos aunque sea comprometido.

### API keys por rol

Cada rol definido en `api/config.yaml` necesita su propia API key en `.env`.

| Variable | Descripción |
|---|---|
| `API_KEY_GERENTE` | Token de acceso del rol gerente |
| `API_KEY_ADMINISTRACION` | Token de acceso del rol administración |
| `API_KEY_RECEPCION` | Token de acceso del rol recepción |

**Cómo generar tokens seguros:**

```bash
openssl rand -hex 32
```

Repetir el comando para cada token. Cada rol debe tener un token distinto.

Si se agregan o eliminan roles en `config.yaml`, agregar o eliminar las variables correspondientes aquí también.

### Modelos LLM

| Variable | Descripción | Valores posibles |
|---|---|---|
| `ANTHROPIC_API_KEY` | Clave de API de Anthropic (Claude) | `sk-ant-api03-...` |
| `CLAUDE_MODEL` | Modelo de Claude para planificación y generación SQL | `claude-haiku-4-5`, `claude-sonnet-4-6` |
| `OLLAMA_MODEL` | Modelo local para síntesis de respuestas | `llama3.2:3b`, `llama3.1:8b` |

> Si `ANTHROPIC_API_KEY` no está configurada o es inválida, la API cae automáticamente a Ollama para todo. La calidad del SQL generado baja pero el sistema sigue funcionando.

### Interfaz web

| Variable | Descripción | Notas |
|---|---|---|
| `WEBUI_SECRET_KEY` | Secret para las sesiones de Open WebUI | Generar con `openssl rand -hex 32` |
| `WEBUI_DEFAULT_MODEL` | Modelo que se muestra por defecto en el chat | Debe coincidir con `business.model_id` en `config.yaml` |
| `ADMINER_HASH` | Hash bcrypt para acceder a Adminer (DB UI) | Ver instrucciones abajo |

**Generar el hash de Adminer:**

```bash
docker run --rm caddy:2-alpine caddy hash-password --plaintext TU_PASSWORD
```

En el archivo `.env`, los `$` del hash deben escribirse como `$$`:

```
ADMINER_HASH=$$2a$$14$$abc123...
```

### Discord (opcional)

| Variable | Descripción |
|---|---|
| `DISCORD_TOKEN` | Token del bot de Discord |
| `DISCORD_CHANNEL_ID` | ID del canal donde el bot escucha y responde |

Si no se usa Discord, dejar estas variables vacías. El contenedor `discord_bot` fallará al iniciar pero no afecta al resto de los servicios.

---

## Archivo `api/config.yaml`

Define el comportamiento del agente para un negocio específico. Se puede modificar y aplicar sin reconstruir el contenedor (solo `docker compose restart api`).

### Sección `business`

```yaml
business:
  name: "Mi Negocio"          # Nombre que aparece en prompts y reportes
  description: "Descripción"  # Descripción breve (aparece en /docs de la API)
  language: "es"              # Idioma de las respuestas
  model_id: "asistente-ia"    # ID del modelo expuesto en /api/v1/models
```

> `model_id` debe coincidir exactamente con `WEBUI_DEFAULT_MODEL` en `.env`.

### Sección `currency`

```yaml
currency:
  symbol: "$"               # Símbolo de la moneda
  thousands_separator: "."  # Separador de miles
  decimal_separator: ","    # Separador decimal
  decimal_places: 0         # 0 = sin decimales (pesos), 2 = con centavos
```

Ejemplos por moneda:

| Moneda | symbol | thousands_separator | decimal_separator | decimal_places |
|---|---|---|---|---|
| Peso chileno | `$` | `.` | `,` | `0` |
| Dólar USD | `$` | `,` | `.` | `2` |
| Euro | `€` | `.` | `,` | `2` |
| Sol peruano | `S/` | `,` | `.` | `2` |

### Sección `roles`

Define quién puede acceder y qué datos puede ver cada rol.

```yaml
roles:
  - name: gerente                   # Nombre del rol (debe coincidir con la variable en .env)
    env_key: API_KEY_GERENTE        # Variable de entorno que contiene el token
    default_key: ger_cambia_esto    # Valor por defecto si la env var no existe (solo desarrollo)
    excluded_tables: []             # Tablas que este rol NO puede consultar

  - name: operaciones
    env_key: API_KEY_OPERACIONES
    default_key: ops_cambia_esto
    excluded_tables:
      - gastos                      # Operaciones no ve gastos ni información financiera sensible
      - categorias_gasto
```

**Cómo agregar un nuevo rol:**

1. Agregar la entrada en `config.yaml` bajo `roles`
2. Agregar la variable `API_KEY_NOMBRE_ROL=token_generado` en `.env`
3. Reiniciar la API: `docker compose restart api`

**Control de acceso por tabla:** `excluded_tables` lista las tablas que el LLM no verá en el schema cuando ese rol hace una consulta. El agente no puede generar SQL sobre tablas que no aparecen en su schema.

### Sección `schema.exclude_tables`

Tablas que **ningún** rol puede ver (infraestructura interna del sistema):

```yaml
schema:
  exclude_tables:
    - audit_log    # Tabla interna de auditoría, nunca expuesta al LLM
```

### Sección `schema.annotations`

Permite enriquecer el schema auto-descubierto con descripciones y hints de dominio. Esto mejora significativamente la calidad del SQL generado.

```yaml
schema:
  annotations:
    nombre_de_tabla:
      description: "Descripción legible de para qué sirve esta tabla"
      columns:
        nombre_columna: "Hint: valores posibles, cómo se calcula, unidad de medida"
```

**Cuándo es importante:**
- Columnas con valores enum (`estado`, `tipo`, `categoria`) — listar los valores posibles
- Columnas calculadas — explicar la fórmula
- Columnas con unidades no obvias — aclarar la unidad

### Sección `kpis`

Define las métricas clave del negocio y cómo calcularlas. El LLM recibe esta información al final del schema.

```yaml
kpis:
  - name: "Nombre del KPI"
    description: "Cómo calcularlo con las tablas disponibles y qué significa"
```

Mientras más precisa sea la descripción (incluyendo nombres de tablas y columnas), mejor será el SQL generado para preguntas sobre ese KPI.

### Secciones `money_columns` y `non_money_columns`

Controlan qué columnas se formatean como moneda en las respuestas.

```yaml
money_columns:
  - monto     # Cualquier columna cuyo nombre contenga "monto" → se formatea como $1.234
  - total
  - precio

non_money_columns:
  - cantidad  # "cantidad" tiene prioridad: aunque contenga "total", no es dinero
  - numero
```

La lógica es: si el nombre de la columna contiene alguna palabra de `money_columns` **y no** contiene ninguna de `non_money_columns`, se formatea como moneda.

### Secciones `income_keywords` y `expense_keywords`

Palabras clave que el sistema usa para pre-calcular el GOP (resultado operativo) antes de sintetizar con Ollama. Clasifican las filas de resultados como ingreso o gasto.

```yaml
income_keywords:
  - ingreso
  - venta
  - cobro

expense_keywords:
  - gasto
  - costo
  - egreso
```

Ajustar según los nombres que usen las tablas del negocio.

### Sección `table_aliases`

Aliases SQL sugeridos al LLM para mantener consistencia en las consultas generadas. No son obligatorios.

```yaml
table_aliases:
  productos: p
  ventas: v
  clientes: c
```

---

## Checklist para un nuevo proyecto

- [ ] Copiar `.env.example` a `.env`
- [ ] Generar tokens con `openssl rand -hex 32` para cada API key y `WEBUI_SECRET_KEY`
- [ ] Configurar `ANTHROPIC_API_KEY` con la clave de Anthropic del cliente
- [ ] Definir `POSTGRES_PASSWORD` y `NEGOCIO_USER_PASSWORD` con valores únicos
- [ ] Generar `ADMINER_HASH` con Caddy
- [ ] Editar `api/config.yaml`:
  - [ ] `business.name` con el nombre del negocio
  - [ ] `business.model_id` (y que coincida con `WEBUI_DEFAULT_MODEL` en `.env`)
  - [ ] `currency` con la moneda del país
  - [ ] `roles` con los perfiles de acceso del cliente
  - [ ] `schema.annotations` con hints del dominio
  - [ ] `kpis` con las métricas relevantes del negocio
  - [ ] `money_columns` / `non_money_columns` según las columnas de su DB
  - [ ] `income_keywords` / `expense_keywords` según terminología del negocio
- [ ] Reemplazar `postgres/init.sql` con el schema real del cliente
- [ ] Reemplazar `postgres/seed.sql` con datos de prueba del cliente (o vaciar)
- [ ] Levantar con `docker compose up -d --build`
- [ ] Verificar con `curl http://localhost:81/app/api/health`
