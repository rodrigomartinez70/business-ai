#!/bin/sh
# Informe Financiero del RESTAURANTE por correo — lunes a las 08:10.
# Mismo patrón que dashboard_semanal.sh (hotel) pero con la key del restaurante.
# Correo financiero ÚNICO top-down. Los destinatarios los resuelve la API
# por-tenant (report.email_to del config).

set -e

FECHA=$(date +%Y-%m-%d)
ARCHIVO="/reportes/informe_financiero_restaurante_${FECHA}.html"

echo "[$(date)] Generando informe financiero (restaurante)..."

curl -sf \
  -H "Authorization: Bearer ${API_KEY_RESTAURANTE}" \
  "http://api:8000/api/agents/informe-financiero?formato=html" \
  -o "$ARCHIVO" && echo "[$(date)] Copia guardada en $ARCHIVO" \
                || echo "[$(date)] WARN: no se pudo guardar la copia HTML (restaurante)."

RESP=$(curl -sf \
  -H "Authorization: Bearer ${API_KEY_RESTAURANTE}" \
  "http://api:8000/api/agents/informe-financiero?formato=email") \
  && echo "[$(date)] Informe financiero restaurante enviado por correo: $RESP" \
  || echo "[$(date)] ERROR: falló el envío del informe de restaurante."

echo "[$(date)] Informe financiero (restaurante) completado."
