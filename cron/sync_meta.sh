#!/bin/sh
# Sync diario de Meta Ads → Postgres (tenant inmobiliaria) — 07:00.
# El cron solo dispara el endpoint; la sincronización (idempotente) la hace la API.
# Sincroniza 120 días para que las comparativas del dashboard tengan cobertura.

set -e

echo "[$(date)] Sync Meta Ads (inmobiliaria)..."

RESP=$(curl -sf -X POST \
  -H "Authorization: Bearer ${API_KEY_INMOBILIARIA}" \
  "http://api:8000/api/integraciones/meta/sync?dias=120") \
  && echo "[$(date)] Sync Meta OK: $RESP" \
  || echo "[$(date)] ERROR: falló el sync de Meta (¿credenciales en public.integraciones?)."

echo "[$(date)] Sync Meta completado."
