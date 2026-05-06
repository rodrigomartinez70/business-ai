#!/bin/sh
# Genera el reporte semanal y lo guarda en /reportes/
# Se ejecuta cada lunes a las 08:00

set -e

FECHA_FIN=$(date +%Y-%m-%d)
FECHA_INICIO=$(date -d "@$(($(date +%s) - 604800))" +%Y-%m-%d)
ARCHIVO="/reportes/reporte_${FECHA_INICIO}_${FECHA_FIN}.md"

echo "[$(date)] Generando reporte $FECHA_INICIO → $FECHA_FIN"

curl -sf \
  -H "Authorization: Bearer ${API_KEY_GERENTE}" \
  "http://api:8000/api/report/weekly?fecha_inicio=${FECHA_INICIO}&fecha_fin=${FECHA_FIN}" \
  -o "$ARCHIVO"

echo "[$(date)] Reporte guardado en $ARCHIVO"
