-- ─────────────────────────────────────────────────────────────
-- Migración 002 — Mover MBI al schema hotel_mbi
--
-- Mueve todas las tablas y secuencias de negocio de public → hotel_mbi.
-- ALTER TABLE ... SET SCHEMA es un cambio de catálogo: instantáneo,
-- sin mover datos en disco, ventana de corte < 1 segundo por tabla.
--
-- Prerequisito: correr 001_control.sql primero.
-- Prerequisito: API en modo MAINTENANCE (retorna 503) durante la ejecución.
-- ─────────────────────────────────────────────────────────────

BEGIN;

-- ── 1. Crear el schema del tenant ────────────────────────────
CREATE SCHEMA IF NOT EXISTS hotel_mbi;

-- ── 2. Mover tablas de negocio ───────────────────────────────
-- Los índices asociados se mueven automáticamente con la tabla.
ALTER TABLE public.habitaciones       SET SCHEMA hotel_mbi;
ALTER TABLE public.canales_venta      SET SCHEMA hotel_mbi;
ALTER TABLE public.huespedes          SET SCHEMA hotel_mbi;
ALTER TABLE public.reservas           SET SCHEMA hotel_mbi;
ALTER TABLE public.pagos              SET SCHEMA hotel_mbi;
ALTER TABLE public.categorias_gasto   SET SCHEMA hotel_mbi;
ALTER TABLE public.gastos             SET SCHEMA hotel_mbi;
ALTER TABLE public.consumos_frigobar  SET SCHEMA hotel_mbi;
ALTER TABLE public.consumos_servicios SET SCHEMA hotel_mbi;
ALTER TABLE public.audit_log          SET SCHEMA hotel_mbi;

-- ── 3. Mover secuencias (SERIAL no se mueve con la tabla) ────
ALTER SEQUENCE public.habitaciones_id_seq       SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.canales_venta_id_seq      SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.huespedes_id_seq          SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.reservas_id_seq           SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.pagos_id_seq              SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.categorias_gasto_id_seq   SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.gastos_id_seq             SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.consumos_frigobar_id_seq  SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.consumos_servicios_id_seq SET SCHEMA hotel_mbi;
ALTER SEQUENCE public.audit_log_id_seq          SET SCHEMA hotel_mbi;

-- ── 4. Permisos sobre el schema del tenant ───────────────────
GRANT USAGE ON SCHEMA hotel_mbi TO negocio_user;
GRANT SELECT              ON ALL TABLES    IN SCHEMA hotel_mbi TO negocio_user;
GRANT INSERT              ON hotel_mbi.audit_log               TO negocio_user;
GRANT USAGE, SELECT       ON ALL SEQUENCES IN SCHEMA hotel_mbi TO negocio_user;

GRANT USAGE ON SCHEMA hotel_mbi TO negocio_ingest;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES    IN SCHEMA hotel_mbi TO negocio_ingest;
GRANT USAGE, SELECT          ON ALL SEQUENCES IN SCHEMA hotel_mbi TO negocio_ingest;

-- ── 5. Registrar MBI como primer tenant ──────────────────────
INSERT INTO public.tenants (id, nombre, vertical, config_path)
VALUES ('hotel_mbi', 'MBI Hotel', 'hotel', '/app/tenants/hotel_mbi/config.yaml')
ON CONFLICT (id) DO NOTHING;

-- Las API keys se insertan con el script de provisioning:
--   python scripts/provision_tenant.py --insert-keys --tenant-id hotel_mbi
-- Los hashes se calculan desde los valores actuales en el .env.

COMMIT;
