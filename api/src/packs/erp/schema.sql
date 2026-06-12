-- ─────────────────────────────────────────────────────────────
-- Pack: erp  (contabilidad importada del ERP)
--
-- Plan de cuentas + saldos mensuales por cuenta. Habilita las fuentes
-- `cuentas:` (tipo/grupo/codigo/id) y el P&L contable.
-- Idempotente (CREATE ... IF NOT EXISTS).
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS plan_cuentas (
    id        SERIAL PRIMARY KEY,
    id_externo VARCHAR(64) UNIQUE,
    codigo    VARCHAR(40),
    nombre    VARCHAR(200),
    tipo      VARCHAR(40),
    grupo     VARCHAR(80)
);

CREATE TABLE IF NOT EXISTS saldos_cuentas (
    id        SERIAL PRIMARY KEY,
    cuenta_id INTEGER NOT NULL REFERENCES plan_cuentas(id),
    anio      SMALLINT NOT NULL,
    mes       SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    debe      NUMERIC(14,2) DEFAULT 0,
    haber     NUMERIC(14,2) DEFAULT 0,
    UNIQUE (cuenta_id, anio, mes)
);
