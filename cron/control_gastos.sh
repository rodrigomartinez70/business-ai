#!/bin/sh
# Control de gastos semanal — se ejecuta los lunes a las 08:30.
# Compara la semana anterior vs la semana previa y envía el reporte a Discord.

set -e

HOY=$(date +%Y-%m-%d)
FECHA_FIN=$(date -d "last sunday" +%Y-%m-%d 2>/dev/null || date -v-sun +%Y-%m-%d)
FECHA_INICIO=$(date -d "$FECHA_FIN - 6 days" +%Y-%m-%d 2>/dev/null || date -v-6d -v-sun +%Y-%m-%d)
ARCHIVO="/reportes/control_gastos_${FECHA_INICIO}_${FECHA_FIN}.json"

echo "[$(date)] Control de gastos ${FECHA_INICIO} → ${FECHA_FIN}..."

RESPONSE=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/control-gastos?fecha_inicio=${FECHA_INICIO}&fecha_fin=${FECHA_FIN}") || {
  echo "[$(date)] ERROR al contactar la API."
  exit 1
}

echo "$RESPONSE" > "$ARCHIVO"
echo "[$(date)] Reporte guardado en $ARCHIVO"

if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  PAYLOAD=$(curl -sf \
    -H "Authorization: Bearer ${API_KEY_GERENTE}" \
    "http://api:8000/api/agents/control-gastos?fecha_inicio=${FECHA_INICIO}&fecha_fin=${FECHA_FIN}&formato=discord_payload")

  curl -sf -X POST "$DISCORD_WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" && echo "[$(date)] Reporte enviado a Discord." \
                  || echo "[$(date)] WARN: no se pudo enviar a Discord."
fi

echo "[$(date)] Control de gastos completado."
