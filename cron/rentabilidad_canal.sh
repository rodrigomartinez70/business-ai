#!/bin/sh
# Rentabilidad por canal mensual — día 1 de cada mes a las 06:30.

set -e

MES_ANT=$(date -d "$(date +%Y-%m-01) -1 day" +%m 2>/dev/null || date -v-1m +%m)
AÑO_ANT=$(date -d "$(date +%Y-%m-01) -1 day" +%Y 2>/dev/null || date -v-1m +%Y)
ARCHIVO="/reportes/rentabilidad_canal_${AÑO_ANT}_${MES_ANT}.json"

echo "[$(date)] Generando rentabilidad por canal ${AÑO_ANT}-${MES_ANT}..."

RESPONSE=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/rentabilidad-canal?mes=${MES_ANT}&anio=${AÑO_ANT}") || {
  echo "[$(date)] ERROR al contactar la API."
  exit 1
}

echo "$RESPONSE" > "$ARCHIVO"

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  PAYLOAD=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/rentabilidad-canal?mes=${MES_ANT}&anio=${AÑO_ANT}&formato=discord_payload")

  curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" && echo "[$(date)] Rentabilidad canal enviada a Discord." \
                  || echo "[$(date)] WARN: no se pudo enviar."
fi

echo "[$(date)] Rentabilidad canal completada."
