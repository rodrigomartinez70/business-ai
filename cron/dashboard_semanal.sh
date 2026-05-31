#!/bin/sh
# Dashboard semanal por correo — se ejecuta los lunes a las 08:00.
# La API genera el HTML, lo envía por SMTP y aquí guardamos una copia local.
# El cron solo dispara: la lógica de envío vive en la API.

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/dashboard_${FECHA}.html"

echo "[$(date)] Generando dashboard semanal..."

# Copia local del HTML (para archivo / respaldo)
curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/dashboard-semanal?formato=html" \
  -o "$ARCHIVO" && echo "[$(date)] Copia guardada en $ARCHIVO" \
                || echo "[$(date)] WARN: no se pudo guardar la copia HTML."

# Envío por correo (la API usa la config SMTP del entorno)
RESP=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/dashboard-semanal?formato=email") \
  && echo "[$(date)] Dashboard enviado por correo: $RESP" \
  || echo "[$(date)] ERROR: falló el envío. ¿Está configurado el SMTP en .env?"

echo "[$(date)] Dashboard semanal completado."
