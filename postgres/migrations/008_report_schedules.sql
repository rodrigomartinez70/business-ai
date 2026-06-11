-- 008_report_schedules.sql — Programación de reportes por correo, gestionable desde MBI Admin.
-- Reemplaza los crons-archivo: un cron lector (cada 15 min) dispara POST /api/admin/schedules/tick,
-- que recorre esta tabla y envía los reportes vencidos. Horarios en hora de Chile.

CREATE TABLE IF NOT EXISTS public.report_schedules (
    id            SERIAL PRIMARY KEY,
    tenant_id     VARCHAR(60) NOT NULL REFERENCES public.tenants(id) ON DELETE CASCADE,
    reporte       VARCHAR(40) NOT NULL DEFAULT 'informe_financiero',
    frecuencia    VARCHAR(20) NOT NULL DEFAULT 'semanal',                 -- 'semanal' (v1)
    dia_semana    SMALLINT    NOT NULL DEFAULT 1 CHECK (dia_semana BETWEEN 1 AND 7),  -- ISO: 1=lunes
    hora          SMALLINT    NOT NULL DEFAULT 9 CHECK (hora BETWEEN 0 AND 23),
    minuto        SMALLINT    NOT NULL DEFAULT 0 CHECK (minuto BETWEEN 0 AND 59),
    destinatarios TEXT,                 -- coma-separados; vacío = usa report.email_to del tenant
    activo        BOOLEAN     DEFAULT TRUE,
    last_run      DATE,                 -- última fecha (Chile) en que se disparó (dedupe)
    created_at    TIMESTAMP   DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_report_schedules_due
    ON public.report_schedules (activo, dia_semana);
