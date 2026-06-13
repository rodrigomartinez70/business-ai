-- 012_doc_clase_rcv.sql — Compra/venta + RUT en documentos_tributarios para la
-- carga del RCV del SII (Fase A: upload CSV, sin certificado).
-- Aplicar POR CADA schema de tenant (SET search_path = <tenant>; \i este archivo).
-- Las filas existentes quedan como 'compra' (eran facturas de compra) → sin cambio
-- en el IVA crédito ya calculado.

ALTER TABLE documentos_tributarios
    ADD COLUMN IF NOT EXISTS clase VARCHAR(10) NOT NULL DEFAULT 'compra';

ALTER TABLE documentos_tributarios
    ADD COLUMN IF NOT EXISTS rut_contraparte VARCHAR(20);

-- Dedup idempotente de cargas de RCV (un DTE = clase+tipo+folio+RUT).
CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_rcv ON documentos_tributarios
    (clase, tipo, numero_documento, rut_contraparte)
    WHERE numero_documento IS NOT NULL AND rut_contraparte IS NOT NULL;
