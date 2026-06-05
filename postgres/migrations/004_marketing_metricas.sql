-- ─────────────────────────────────────────────────────────────
-- Migración 004 — Métricas adicionales de Meta Ads en insights_marketing
--
-- Agrega columnas para mensajes, interacciones, reproducciones y visitas al perfil.
-- Idempotente (ADD COLUMN IF NOT EXISTS).
--
-- IMPORTANTE: insights_marketing vive en el schema de CADA tenant. Ejecutar con
-- search_path apuntando al tenant, p.ej.:
--   SET search_path = inmobiliaria, public;  \i 004_marketing_metricas.sql
-- (repetir por cada tenant con esquema de marketing).
-- ─────────────────────────────────────────────────────────────

ALTER TABLE insights_marketing ADD COLUMN IF NOT EXISTS mensajes       BIGINT DEFAULT 0;
ALTER TABLE insights_marketing ADD COLUMN IF NOT EXISTS interacciones  BIGINT DEFAULT 0;
ALTER TABLE insights_marketing ADD COLUMN IF NOT EXISTS reproducciones BIGINT DEFAULT 0;
ALTER TABLE insights_marketing ADD COLUMN IF NOT EXISTS visitas_perfil BIGINT DEFAULT 0;
