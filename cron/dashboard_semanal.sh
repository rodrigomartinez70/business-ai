#!/bin/sh
# Informe Financiero (hotel) por correo — se ejecuta los lunes a las 08:00.
# Correo financiero ÚNICO top-down: fusiona el dashboard semanal con el panel
# financiero (CFO, Tesorería, CxC/CxP, Presupuesto). La lógica vive en la API.

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/informe_financiero_${FECHA}.html"

echo "[$(date)] Generando informe financiero (hotel)..."

# Copia local del HTML (para archivo / respaldo)
curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/informe-financiero?formato=html" \
  -o "$ARCHIVO" && echo "[$(date)] Copia guardada en $ARCHIVO" \
                || echo "[$(date)] WARN: no se pudo guardar la copia HTML."

# Envío por correo (la API usa la config SMTP del entorno)
RESP=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/agents/informe-financiero?formato=email") \
  && echo "[$(date)] Informe financiero enviado por correo: $RESP" \
  || echo "[$(date)] ERROR: falló el envío. ¿Está configurado el SMTP en .env?"

echo "[$(date)] Informe financiero (hotel) completado."
