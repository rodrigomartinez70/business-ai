#!/bin/sh
# Verifica KPIs diariamente y postea a Discord si hay alertas activas.
#
# Variables requeridas en el entorno (definidas en docker-compose.yml):
#   API_KEY_GERENTE     — token con acceso al endpoint de alertas
#   DISCORD_WEBHOOK_URL — URL del webhook de Discord (opcional; si está vacía no se envía nada)

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/alertas_${FECHA}.json"
PERIODO_DIAS=${PERIODO_DIAS:-7}

echo "[$(date)] Verificando KPIs (período: ${PERIODO_DIAS} días)..."

RESPONSE=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/alertas?periodo_dias=${PERIODO_DIAS}") || {
  echo "[$(date)] ERROR: No se pudo contactar la API — reintentando en 60s..."
  sleep 60
  RESPONSE=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/alertas?periodo_dias=${PERIODO_DIAS}") || {
    echo "[$(date)] ERROR: segundo intento fallido. Abortando."
    exit 1
  }
}

echo "$RESPONSE" > "$ARCHIVO"

# Extraer alertas_activas del JSON sin jq
ALERTAS=$(echo "$RESPONSE" | grep -o '"alertas_activas":[0-9]*' | grep -o '[0-9]*$')
ALERTAS=${ALERTAS:-0}

echo "[$(date)] Alertas activas: ${ALERTAS}"

if [ "$ALERTAS" -gt 0 ] && [ -n "$DISCORD_WEBHOOK_URL" ]; then
  echo "[$(date)] Obteniendo payload para Discord..."

  # El endpoint devuelve el JSON listo para postear al webhook
  PAYLOAD=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/alertas?periodo_dias=${PERIODO_DIAS}&formato=discord_payload")

  curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" && echo "[$(date)] Alerta enviada a Discord." \
                  || echo "[$(date)] WARN: no se pudo enviar a Discord."
fi

echo "[$(date)] Verificación completada. Reporte: ${ARCHIVO}"
