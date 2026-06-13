-- Usuarios del dashboard web POR EMPRESA (distinto de public.admin_users, que es
-- el back-office cross-tenant). Cada empresa gestiona sus propios usuarios; el
-- borrado de la empresa (DROP) limpia los suyos por ON DELETE CASCADE.
CREATE TABLE IF NOT EXISTS public.dashboard_users (
    id            SERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    email         TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    activo        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, email)
);
CREATE INDEX IF NOT EXISTS idx_dashboard_users_tenant ON public.dashboard_users(tenant_id);
