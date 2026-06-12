-- 011_tenant_packs.sql — Packs de datos componibles por tenant.
-- Una empresa pasa a definirse por la composición de sus packs (base + POS/ERP/…)
-- en vez de un único `vertical`. Ver doc/design-packs.md. Fase P1: se agrega la
-- columna y se backfillea desde el vertical histórico (mapeo 1:1, sin cambio visible).

ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS packs text[];

COMMENT ON COLUMN public.tenants.packs IS
  'Packs de datos activos (base, pos_gastronomico, pos_hotelero, erp). Estructural: '
  'determina las tablas del schema y las fuentes disponibles. NULL = derivar del vertical.';

-- Backfill 1:1 desde el vertical (solo donde packs aún es NULL).
UPDATE public.tenants
   SET packs = ARRAY['base', 'pos_gastronomico', 'erp']
 WHERE packs IS NULL AND vertical = 'restaurante';

UPDATE public.tenants
   SET packs = ARRAY['base', 'pos_hotelero', 'erp']
 WHERE packs IS NULL AND vertical = 'hotel';

-- Verticales sin mapeo conocido: al menos base.
UPDATE public.tenants
   SET packs = ARRAY['base']
 WHERE packs IS NULL;
