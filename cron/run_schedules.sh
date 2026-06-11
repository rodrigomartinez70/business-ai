#!/bin/sh
# Cron lector del scheduler de reportes. Cada ~15 min golpea el tick de la API,
# que envía los reportes programados (public.report_schedules) ya vencidos.
# La lógica (qué enviar, a quién, dedupe por last_run) vive en la API.

set -e

RESP=$(curl -sf -u "${ADMIN_USER}:${ADMIN_PASSWORD}" -X POST \
  "http://api:8000/api/admin/schedules/tick") \
  && echo "[$(date)] schedules tick: $RESP" \
  || echo "[$(date)] ERROR: falló el tick del scheduler (¿ADMIN_PASSWORD en el cron?)."
