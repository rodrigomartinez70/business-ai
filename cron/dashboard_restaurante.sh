#!/bin/sh
# Dashboard semanal del RESTAURANTE por correo — lunes a las 08:10.
# Mismo patrón que dashboard_semanal.sh (hotel) pero con la key del restaurante.
# Los destinatarios los resuelve la API por-tenant (report.email_to del config).

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/dashboard_restaurante_${FECHA}.html"

echo "[$(date)] Generando dashboard semanal (restaurante)..."

curl -sf \
  -H "Authorization: Bearer ${API_KEY_RESTAURANTE}" \
  "http://api:8000/api/agents/dashboard-semanal?formato=html" \
  -o "$ARCHIVO" && echo "[$(date)] Copia guardada en $ARCHIVO" \
                || echo "[$(date)] WARN: no se pudo guardar la copia HTML (restaurante)."

RESP=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_RESTAURANTE}" \
  "http://api:8000/api/agents/dashboard-semanal?formato=email") \
  && echo "[$(date)] Dashboard restaurante enviado por correo: $RESP" \
  || echo "[$(date)] ERROR: falló el envío del dashboard de restaurante."

echo "[$(date)] Dashboard semanal (restaurante) completado."
