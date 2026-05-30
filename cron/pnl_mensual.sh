#!/bin/sh
# P&L Mensual — se ejecuta el día 1 de cada mes a las 06:00.
# Genera el P&L del mes cerrado y lo envía a Discord.

set -e

HOY=$(date +%Y-%m-%d)
# Mes anterior al actual
MES_ANT=$(date -d "$(date +%Y-%m-01) -1 day" +%m 2>/dev/null || date -v-1m +%m)
AÑO_ANT=$(date -d "$(date +%Y-%m-01) -1 day" +%Y 2>/dev/null || date -v-1m +%Y)
ARCHIVO="/reportes/pnl_${AÑO_ANT}_${MES_ANT}.json"

echo "[$(date)] Generando P&L ${AÑO_ANT}-${MES_ANT}..."

RESPONSE=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/pnl-mensual?mes=${MES_ANT}&año=${AÑO_ANT}") || {
  echo "[$(date)] ERROR al contactar la API."
  exit 1
}

echo "$RESPONSE" > "$ARCHIVO"
echo "[$(date)] P&L guardado en $ARCHIVO"

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  PAYLOAD=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/pnl-mensual?mes=${MES_ANT}&año=${AÑO_ANT}&formato=discord_payload")

  curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" && echo "[$(date)] P&L enviado a Discord." \
                  || echo "[$(date)] WARN: no se pudo enviar a Discord."
fi

echo "[$(date)] P&L mensual completado."
