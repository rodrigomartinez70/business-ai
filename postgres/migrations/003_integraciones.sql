-- ─────────────────────────────────────────────────────────────
-- Migración 003 — Credenciales de integraciones externas (por tenant)
--
-- Guarda las credenciales de plataformas externas (Meta Ads, etc.) por tenant.
-- El access_token es SECRETO: NO se otorga acceso a negocio_user (solo el
-- conector/script de sincronización lo lee con credenciales de administración).
-- Idempotente.
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.integraciones (
    id             SERIAL PRIMARY KEY,
    tenant_id      VARCHAR(60) NOT NULL REFERENCES public.tenants(id),
    proveedor      VARCHAR(40) NOT NULL,        -- 'meta'
    access_token   TEXT,                        -- SECRETO (idealmente cifrado en reposo)
    cuenta_id      VARCHAR(80),                 -- Ad Account ID, ej. 'act_1234567890'
    config         JSONB DEFAULT '{}'::jsonb,   -- params extra (api_version, form_ids, ...)
    activo         BOOLEAN DEFAULT TRUE,
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, proveedor)
);

CREATE INDEX IF NOT EXISTS idx_integraciones_tenant ON public.integraciones(tenant_id);
