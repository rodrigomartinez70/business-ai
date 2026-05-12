# Onboarding — business-ai

Plataforma de análisis de negocio con IA para hoteles. Permite a los operadores hacer preguntas en lenguaje natural sobre sus datos operativos y financieros, sin escribir SQL.

---

## Qué hace el sistema

1. El usuario escribe una pregunta en lenguaje natural en Open WebUI (ej: "¿cuál fue la ocupación del mes pasado?")
2. La API convierte la pregunta a SQL usando Claude (Anthropic) o un modelo local via Ollama
3. El SQL se ejecuta contra la base de datos PostgreSQL
4. El resultado se formatea y devuelve al usuario

Además corre un cron diario a las 07:00 que evalúa KPIs operativos (ocupación, pickup, cancelaciones) y envía alertas a Discord si alguno supera los umbrales definidos.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| API | FastAPI + asyncpg |
| Base de datos | PostgreSQL 16 |
| LLM principal | Claude (Anthropic API) |
| LLM fallback | Ollama (local) |
| Frontend | Open WebUI v0.9.5 |
| Reverse proxy | Caddy |
| Alertas | Discord webhook |
| CI/CD | GitHub Actions → rsync → Docker |
| Servidor | Hetzner CPX32, Ubuntu 22.04 |

---

## Estructura del proyecto

```
business-ai/
├── api/
│   ├── src/
│   │   ├── main.py          # FastAPI app, lifespan (DB pool, schema cache)
│   │   ├── agent.py         # Generación de SQL con Claude/Ollama
│   │   ├── config.py        # Carga de config.yaml y variables de entorno
│   │   ├── formatting.py    # Formatea resultados SQL → markdown
│   │   ├── auth.py          # API keys por rol
│   │   ├── schema.py        # Introspección del schema PostgreSQL
│   │   ├── audit.py         # Registro de consultas en audit_log
│   │   ├── routers/
│   │   │   ├── chat.py      # Endpoints compatibles Open WebUI (/api/v1/chat/completions)
│   │   │   ├── agents.py    # Endpoint de alertas KPI (/api/agents/alertas)
│   │   │   ├── reports.py   # Reporte semanal (/api/report/weekly)
│   │   │   └── ingest.py    # Carga de CSV (/api/ingest/*)
│   │   └── agents/
│   │       └── alertas.py   # Lógica de KPIs y umbrales (sin LLM)
│   ├── config.yaml          # Configuración del negocio (KPIs, roles, moneda, schema)
│   ├── sql_guidelines.md    # Instrucciones SQL inyectadas al LLM
│   └── requirements.txt
├── postgres/
│   ├── init.sql             # Schema completo + roles PostgreSQL
│   └── seed.sql             # Datos maestros (habitaciones, canales, categorías)
├── scripts/
│   ├── generar_datos.py     # Genera datos fake con patrones estacionales
│   └── Dockerfile
├── cron/
│   ├── alertas_diarias.sh   # Evalúa KPIs y postea a Discord si hay alertas
│   └── crontab              # 07:00 diario
├── discord_bot/
│   ├── bot.py               # Bot interactivo (secundario, puede desactivarse)
│   └── Dockerfile
├── caddy/
│   └── Caddyfile            # Reverse proxy → puerto 81
├── docker-compose.yml       # Stack completo
├── docker-compose.test.yml  # Stack de tests (PostgreSQL en puerto 5435)
└── .github/workflows/
    └── tests.yml            # CI: tests → deploy por rsync
```

---

## Setup local (desarrollo)

### Requisitos
- Python 3.11+
- Docker Desktop

### Pasos

```sh
# 1. Clonar
git clone https://github.com/rodrigomartinez70/business-ai.git
cd business-ai

# 2. Instalar dependencias
pip install -r api/requirements.txt -r requirements-test.txt

# 3. Levantar la base de datos de tests
docker compose -f docker-compose.test.yml up -d --wait

# 4. Correr los tests
cd api
DATABASE_URL="postgresql://test_admin:test_password@localhost:5435/test_negocio_db" \
INGEST_DATABASE_URL="postgresql://test_admin:test_password@localhost:5435/test_negocio_db" \
BUSINESS_CONFIG_PATH="api/config.yaml" \
API_KEY_GERENTE="test-key-gerente" \
API_KEY_ADMINISTRACION="test-key-admin" \
API_KEY_RECEPCION="test-key-recepcion" \
ANTHROPIC_API_KEY="" \
OLLAMA_URL="http://localhost:11434" \
python3 -m pytest ../tests/ -v

# 5. Apagar la base de datos
cd .. && docker compose -f docker-compose.test.yml down
```

---

## Configuración del negocio (`api/config.yaml`)

Este archivo controla todo el comportamiento específico del negocio. **No requiere rebuild** — está montado como volumen en producción; alcanza con `docker compose restart api`.

Secciones clave:

- **`business`** — nombre, idioma, model_id expuesto a Open WebUI
- **`currency`** — símbolo, separadores de miles/decimal
- **`roles`** — nombres de rol + variable de entorno de su API key
- **`schema.annotations`** — descripciones de tablas/columnas para el LLM
- **`kpis`** — KPIs con SQL, umbrales warning/crítico para las alertas diarias
- **`money_columns`** / **`non_money_columns`** — controlan el formateo de moneda

### KPIs actuales

| KPI | Período | Warning | Crítico |
|-----|---------|---------|---------|
| Ocupación próximos 7 días | Forward 7 días | < 50% | < 35% |
| Pickup últimos 7 días | Últimos 7 días | < 10 reservas | < 5 reservas |
| Cancelaciones últimas 24h | Últimas 24h | > 2 | > 4 |

---

## Cómo funciona el pipeline de texto a SQL

1. `chat.py` recibe la pregunta del usuario
2. Llama a `generar_plan()` — si la pregunta requiere múltiples consultas, Claude arma un plan de pasos
3. Si no hay plan, llama a `generar_sql()` — Claude genera el SQL con el schema + `sql_guidelines.md` como contexto
4. El SQL se ejecuta con `ejecutar_sql()` (solo SELECT, rol-aware)
5. El resultado se formatea en `formatting.py` → tabla markdown o lista de valores

El historial de conversación se pasa a Claude para que entienda preguntas de seguimiento ("¿y el mes anterior?").

---

## Roles y autenticación

Tres roles definidos en `config.yaml`, cada uno con su API key en `.env`:

| Rol | Acceso |
|-----|--------|
| `gerente` | Todo |
| `administracion` | Todo |
| `recepcion` | Sin gastos ni canales |

La API key va en el header: `Authorization: Bearer <API_KEY>`

---

## Deploy

El CI/CD corre automáticamente en cada push a `main`:
1. Tests contra PostgreSQL en Docker
2. Si pasan, rsync de los archivos al servidor
3. Rebuild del contenedor `api`
4. Health check

**Qué se sincroniza:** `api/src/`, `api/requirements.txt`, `api/Dockerfile`, `api/sql_guidelines.md`, `api/config.yaml`, `scripts/`, `cron/`

**Qué NO se sincroniza:** `docker-compose.yml`, `.env`, `postgres/` (datos de producción)

El servidor está en Hetzner — acceso SSH con la clave `~/.ssh/hetzner_colegio` (pedirle a Rodrigo).

---

## Variables de entorno (`.env`)

Copiar `.env.example` y completar. Las críticas:

| Variable | Descripción |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Clave de Anthropic para Claude |
| `API_KEY_GERENTE` | Token de acceso para el rol gerente |
| `DISCORD_WEBHOOK_URL` | URL del webhook de Discord para alertas |
| `POSTGRES_PASSWORD` | Contraseña del superusuario PostgreSQL |

Generar tokens seguros con: `openssl rand -hex 32`

---

## Trabajar con Claude Code

Este proyecto usa Claude Code como herramienta de desarrollo. El `CLAUDE.md` en la raíz tiene las instrucciones del proyecto que Claude lee automáticamente.

```sh
# Instalar
npm install -g @anthropic/claude-code

# Entrar al proyecto y arrancar
cd business-ai
claude
```

Convenciones importantes que Claude ya conoce:
- Tests de integración con DB real (no mocks)
- Queries parametrizadas siempre (sin concatenación de strings)
- `config.yaml` como única fuente de verdad de la configuración del negocio
- No agregar comentarios salvo que el "por qué" sea no obvio
