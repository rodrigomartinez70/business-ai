-- Reglas de categorización de proveedores (por empresa): mapea cada proveedor
-- del RCV de compras a una categoría de gasto OPEX, y marca los de comida
-- (insumos) para EXCLUIRLOS del control de gastos (ya son food cost / COGS del POS).
CREATE TABLE IF NOT EXISTS categorias_proveedor (
    id         SERIAL PRIMARY KEY,
    proveedor  VARCHAR(150) UNIQUE NOT NULL,
    categoria  VARCHAR(100),                      -- categorias_gasto.nombre (OPEX)
    es_comida  BOOLEAN NOT NULL DEFAULT FALSE,    -- true = insumo de comida (COGS) → excluir de OPEX
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
