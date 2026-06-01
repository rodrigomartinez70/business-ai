-- ─────────────────────────────────────────────────────────────
-- Migración 001 — Tablas de control de la plataforma multi-tenant
--
-- Crea las tablas de plataforma en el schema public.
-- No toca ninguna tabla de negocio existente.
-- Idempotente: se puede correr más de una vez sin error.
-- ─────────────────────────────────────────────────────────────

-- Registro de clientes (tenants)
CREATE TABLE IF NOT EXISTS public.tenants (
    id           VARCHAR(60)  PRIMARY KEY,       -- 'hotel_mbi', 'restaurante_xyz'
    nombre       VARCHAR(200) NOT NULL,
    vertical     VARCHAR(50)  NOT NULL,           -- 'hotel', 'restaurante'
    config_path  VARCHAR(500) NOT NULL,           -- ruta al config.yaml del tenant en el container
    activo       BOOLEAN      DEFAULT TRUE,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- API keys de autenticación (guardadas como SHA-256, nunca en texto plano)
CREATE TABLE IF NOT EXISTS public.api_keys (
    key_hash     VARCHAR(64)  PRIMARY KEY,        -- SHA-256 hex de la clave real
    tenant_id    VARCHAR(60)  NOT NULL REFERENCES public.tenants(id),
    rol          VARCHAR(50)  NOT NULL,            -- 'gerente', 'administracion', 'recepcion'
    descripcion  VARCHAR(200),
    activa       BOOLEAN      DEFAULT TRUE,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON public.api_keys(tenant_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_activa ON public.api_keys(activa);
