#!/bin/sh
# Revenue Management diario — se ejecuta todos los días a las 08:00.
# Envía snapshot de ocupación, ADR, RevPAR y proyección a Discord.

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/revenue_${FECHA}.json"

echo "[$(date)] Generando revenue management ${FECHA}..."

RESPONSE=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/revenue-management?horizon_dias=30") || {
  echo "[$(date)] ERROR al contactar la API."
  exit 1
}

echo "$RESPONSE" > "$ARCHIVO"
echo "[$(date)] Reporte guardado en $ARCHIVO"

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  PAYLOAD=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/revenue-management?horizon_dias=30&formato=discord_payload")

  curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" && echo "[$(date)] Revenue management enviado a Discord." \
                  || echo "[$(date)] WARN: no se pudo enviar a Discord."
fi

echo "[$(date)] Revenue management completado."
