#!/bin/sh
# Cierre diario — se ejecuta todos los días a las 23:00.
# Genera el resumen del día y lo envía a Discord via webhook.
#
# Variables requeridas (definidas en docker-compose.yml):
#   API_KEY_GERENTE     — token de acceso
#   DISCORD_WEBHOOK_URL — URL del webhook (vacío = no enviar a Discord)

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/cierre_${FECHA}.json"

echo "[$(date)] Generando cierre diario ${FECHA}..."

RESPONSE=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/cierre-diario?fecha=${FECHA}") || {
  echo "[$(date)] ERROR: No se pudo contactar la API — reintentando en 60s..."
  sleep 60
  RESPONSE=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/cierre-diario?fecha=${FECHA}") || {
    echo "[$(date)] ERROR: segundo intento fallido. Abortando."
    exit 1
  }
}

echo "$RESPONSE" > "$ARCHIVO"
echo "[$(date)] Cierre guardado en $ARCHIVO"

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  echo "[$(date)] Enviando a Discord..."

  PAYLOAD=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/cierre-diario?fecha=${FECHA}&formato=discord_payload")

  curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" && echo "[$(date)] Cierre enviado a Discord." \
                  || echo "[$(date)] WARN: no se pudo enviar a Discord."
fi

echo "[$(date)] Cierre diario completado."
