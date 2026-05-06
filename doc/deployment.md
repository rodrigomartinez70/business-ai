# Guía de despliegue en VM

Pasos para poner en producción la plataforma IA en una máquina virtual desde cero.

---

## Requisitos de la VM

| Recurso | Mínimo | Recomendado |
|---|---|---|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GB | 8 GB |
| Disco | 20 GB | 40 GB |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Puertos abiertos | 81, 444 | 81, 444 |

> Si se usa Ollama local (modelo LLM corriendo en la VM), sumar 8 GB de RAM y 10 GB de disco por modelo.

---

## 1. Instalar Docker

```bash
# Actualizar paquetes
sudo apt update && sudo apt upgrade -y

# Instalar dependencias
sudo apt install -y ca-certificates curl gnupg

# Agregar repositorio oficial de Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Permitir usar docker sin sudo
sudo usermod -aG docker $USER
newgrp docker

# Verificar instalación
docker --version
docker compose version
```

---

## 2. Clonar el proyecto

```bash
# Crear directorio de trabajo
mkdir -p ~/proyectos && cd ~/proyectos

# Clonar el repositorio
git clone <URL_DEL_REPOSITORIO> ia-negocio
cd ia-negocio
```

---

## 3. Configurar variables de entorno

```bash
# Copiar el archivo de ejemplo
cp .env.example .env

# Editar con los valores reales
nano .env
```

Ver `doc/configuration.md` para el detalle de cada variable.

### Generar tokens seguros

Para las API keys y el secret de la web UI, usar:

```bash
# Generar un token aleatorio de 32 bytes (repetir para cada API key)
openssl rand -hex 32
```

### Generar el hash de Adminer

Adminer (interfaz web de la base de datos) requiere un hash bcrypt para la autenticación:

```bash
# Ejecutar caddy dentro de un contenedor temporal
docker run --rm caddy:2-alpine caddy hash-password --plaintext TU_PASSWORD_AQUI
```

Copiar el resultado en `.env` como `ADMINER_HASH`. Los `$` deben escaparse como `$$` en el archivo `.env`.

---

## 4. Construir y levantar los servicios

```bash
# Construir imágenes y levantar todos los servicios en segundo plano
docker compose up -d --build
```

La primera vez tarda varios minutos porque:
- Descarga las imágenes base de Docker Hub
- Construye la imagen de la API
- Inicializa la base de datos PostgreSQL con el schema y datos de prueba

### Verificar que todo arrancó correctamente

```bash
# Ver el estado de todos los contenedores
docker compose ps

# Ver los logs en tiempo real
docker compose logs -f

# Verificar solo la API
docker compose logs api --tail=30
```

La API está lista cuando aparece en los logs:

```
Conexión a PostgreSQL establecida.
Schema cache construido para roles: [...]
INFO:     Application startup complete.
```

---

## 5. Verificar el despliegue

### Health check de la API

```bash
curl -s http://localhost:81/app/api/health | python3 -m json.tool
```

Respuesta esperada:
```json
{
  "status": "ok",
  "db": "conectada",
  "modelo": "llama3.2:3b"
}
```

### Acceder a la interfaz web

Abrir en el navegador: `http://IP_DE_LA_VM:81`

Se mostrará Open WebUI, la interfaz de chat. Las credenciales se configuran la primera vez.

### Acceder a Adminer (gestión de base de datos)

URL: `http://IP_DE_LA_VM:81/adminer/`

Credenciales:
- Usuario: `admin`
- Contraseña: la definida al generar `ADMINER_HASH`

---

## 6. Operaciones comunes

### Reiniciar un servicio específico

```bash
docker compose restart api
docker compose restart discord_bot
```

### Ver logs de un servicio

```bash
docker compose logs api -f --tail=100
docker compose logs postgres -f --tail=50
```

### Detener todo

```bash
docker compose down
```

### Detener y eliminar volúmenes (⚠ borra los datos de la DB)

```bash
docker compose down -v
```

### Actualizar el código sin perder datos

```bash
git pull
docker compose up -d --build api
```

Solo reconstruye el contenedor de la API; la base de datos y sus datos se mantienen.

### Actualizar la configuración del negocio sin rebuild

`api/config.yaml` está montado como volumen. Para aplicar cambios basta con reiniciar la API:

```bash
# Editar config
nano api/config.yaml

# Aplicar sin rebuild
docker compose restart api
```

---

## 7. Configurar HTTPS (opcional pero recomendado en producción)

Caddy maneja HTTPS automáticamente si se le provee un dominio. Editar `caddy/Caddyfile`:

```
tu.dominio.com {
    handle /app/* {
        uri strip_prefix /app
        reverse_proxy api:8000
    }
    handle /adminer/* {
        basic_auth {
            admin {$ADMINER_HASH}
        }
        uri strip_prefix /adminer
        reverse_proxy adminer:8080
    }
    handle {
        reverse_proxy open-webui:8080
    }
}
```

Y cambiar los puertos en `docker-compose.yml`:

```yaml
caddy:
  ports:
    - "80:80"
    - "443:443"
```

Caddy obtiene y renueva el certificado TLS de Let's Encrypt automáticamente.

---

## 8. Configurar Ollama externo (opcional)

Si Ollama corre en otra máquina o ya existe en la infraestructura:

En `.env`:
```
# Apuntar a la URL del Ollama compartido
OLLAMA_URL=http://IP_OLLAMA:11434
OLLAMA_MODEL=llama3.2:3b
```

No es necesario levantar ningún servicio Ollama adicional en esta VM.

---

## Resolución de problemas

### La API no conecta a PostgreSQL

```bash
# Ver si postgres está healthy
docker compose ps postgres

# Ver logs de postgres
docker compose logs postgres --tail=50
```

Verificar que `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` en `.env` coincidan con los valores en `postgres/init.sql`.

### Open WebUI no muestra el modelo del agente

Verificar que `WEBUI_DEFAULT_MODEL` en `.env` coincida exactamente con `business.model_id` en `api/config.yaml`.

### Errores de permisos en Docker

```bash
# Si aparece "permission denied" al ejecutar docker
sudo usermod -aG docker $USER && newgrp docker
```
