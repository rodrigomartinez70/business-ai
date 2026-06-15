#!/bin/sh
# Sync diario de Toteat → vertical restaurante (restaurante_toteat) — 07:30.
# Incremental: ventana de 7 días (idempotente, atrapa turnos que cierran tarde).
# REAL: usa las credenciales de public.integraciones (xapitoken/xir/xil/xiu).

set -e

echo "[$(date)] Sync Toteat (restaurante_toteat)..."

RESP=$(curl -sf -X POST \
  -H "Authorization: Bearer ${API_KEY_RESTAURANTE_TOTEAT}" \
  "http://api:8000/api/integraciones/toteat/sync?dias=7") \
  && echo "[$(date)] Sync Toteat OK: $RESP" \
  || echo "[$(date)] ERROR: falló el sync de Toteat (¿credenciales en public.integraciones?)."

echo "[$(date)] Sync Toteat completado."
