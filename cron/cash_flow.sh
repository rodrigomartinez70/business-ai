#!/bin/sh
# Cash Flow semanal — se ejecuta los lunes a las 07:30.
# Envía la proyección de las próximas 8 semanas a Discord.

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/cash_flow_${FECHA}.json"

echo "[$(date)] Generando cash flow ${FECHA}..."

RESPONSE=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/cash-flow") || {
  echo "[$(date)] ERROR al contactar la API."
  exit 1
}

echo "$RESPONSE" > "$ARCHIVO"
echo "[$(date)] Cash flow guardado en $ARCHIVO"

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  PAYLOAD=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/cash-flow?formato=discord_payload")

  curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" && echo "[$(date)] Cash flow enviado a Discord." \
                  || echo "[$(date)] WARN: no se pudo enviar a Discord."
fi

echo "[$(date)] Cash flow completado."
