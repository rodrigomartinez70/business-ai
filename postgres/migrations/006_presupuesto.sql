-- 006_presupuesto.sql — tabla de presupuesto para el Agente Presupuestario.
-- Horizontal (misma estructura en todos los verticales). Aplicar por cada schema de tenant:
--   SET search_path TO <tenant>; \i 006_presupuesto.sql
-- Una fila por (año, mes, categoría, tipo). tipo: 'ingreso' presupuestado o 'gasto' por categoría.

CREATE TABLE IF NOT EXISTS presupuesto (
    id        SERIAL PRIMARY KEY,
    anio      INTEGER       NOT NULL,
    mes       INTEGER       NOT NULL CHECK (mes BETWEEN 1 AND 12),
    tipo      VARCHAR(20)   NOT NULL DEFAULT 'gasto' CHECK (tipo IN ('ingreso', 'gasto')),
    categoria VARCHAR(100)  NOT NULL,                 -- 'ingresos' o nombre de categoría de gasto
    monto     NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (anio, mes, tipo, categoria)
);

CREATE INDEX IF NOT EXISTS idx_presupuesto_periodo ON presupuesto(anio, mes);
