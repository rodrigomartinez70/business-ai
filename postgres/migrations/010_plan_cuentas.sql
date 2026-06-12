-- 010_plan_cuentas.sql — Mayor contable para el P&L desde ERP (Odoo/Defontana).
-- Aplicar por cada schema de tenant que tenga (o vaya a tener) un ERP conectado.

CREATE TABLE IF NOT EXISTS plan_cuentas (
    id          SERIAL PRIMARY KEY,
    id_externo  VARCHAR(64) UNIQUE,            -- id de la cuenta en el ERP
    codigo      VARCHAR(40),                   -- '4.1.01'
    nombre      VARCHAR(200),
    tipo        VARCHAR(40),                   -- income | cogs | expense | tax | otro
    grupo       VARCHAR(80)                    -- agrupador ('6.2'), opcional
);

CREATE TABLE IF NOT EXISTS saldos_cuentas (
    id         SERIAL PRIMARY KEY,
    cuenta_id  INTEGER NOT NULL REFERENCES plan_cuentas(id),
    anio       SMALLINT NOT NULL,
    mes        SMALLINT NOT NULL CHECK (mes BETWEEN 1 AND 12),
    debe       NUMERIC(14,2) DEFAULT 0,        -- movimiento del período (no acumulado)
    haber      NUMERIC(14,2) DEFAULT 0,
    UNIQUE (cuenta_id, anio, mes)
);

CREATE INDEX IF NOT EXISTS idx_saldos_periodo ON saldos_cuentas(anio, mes);
