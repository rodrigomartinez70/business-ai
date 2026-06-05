-- ─────────────────────────────────────────────────────────────
-- Migración 005 — id_externo en productos/pedidos (integración Toteat)
--
-- Permite upsert idempotente de productos y órdenes traídos del POS Toteat.
-- Idempotente. Ejecutar con search_path en el schema del tenant restaurante:
--   SET search_path = restaurante_xyz, public;  \i 005_toteat_id_externo.sql
-- ─────────────────────────────────────────────────────────────

ALTER TABLE productos ADD COLUMN IF NOT EXISTS id_externo VARCHAR(64);
ALTER TABLE pedidos   ADD COLUMN IF NOT EXISTS id_externo VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS ux_productos_id_externo ON productos(id_externo) WHERE id_externo IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_id_externo   ON pedidos(id_externo)   WHERE id_externo IS NOT NULL;
