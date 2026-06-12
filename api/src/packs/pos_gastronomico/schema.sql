-- ─────────────────────────────────────────────────────────────
-- Pack: pos_gastronomico  (POS de restaurante: Toteat u otro)
--
-- Menú, pedidos y cobros del punto de venta gastronómico. Habilita las
-- fuentes de Ventas POS (ventas, n_pedidos, propinas, ventas_por_canal,
-- top_productos) y el Cierre diario.
-- Idempotente (CREATE ... IF NOT EXISTS).
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mesas (
    id          SERIAL PRIMARY KEY,
    numero      VARCHAR(10) UNIQUE NOT NULL,
    capacidad   INTEGER DEFAULT 4,
    sector      VARCHAR(50),                 -- 'Salón', 'Terraza', 'Barra', 'Privado'
    activa      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS canales_venta (
    id           SERIAL PRIMARY KEY,
    nombre       VARCHAR(100) NOT NULL,       -- 'Salón', 'Delivery', 'Takeaway', 'Rappi', 'PedidosYa', 'Uber Eats'
    comision_pct NUMERIC(5,2) DEFAULT 0,
    activo       BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS categorias_menu (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL,        -- 'Entradas', 'Platos de fondo', 'Bebidas', 'Postres', 'Vinos'
    descripcion TEXT
);

CREATE TABLE IF NOT EXISTS productos (
    id           SERIAL PRIMARY KEY,
    id_externo   VARCHAR(64),                 -- id en POS externo (Toteat) para upsert idempotente
    categoria_id INTEGER REFERENCES categorias_menu(id),
    nombre       VARCHAR(120) NOT NULL,
    precio       NUMERIC(10,2) NOT NULL,
    costo        NUMERIC(10,2) NOT NULL DEFAULT 0,
    activo       BOOLEAN DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pedidos (
    id            SERIAL PRIMARY KEY,
    id_externo    VARCHAR(64),                           -- id de orden en POS externo (Toteat)
    mesa_id       INTEGER REFERENCES mesas(id),          -- NULL si es delivery/takeaway
    canal_id      INTEGER REFERENCES canales_venta(id),
    fecha         DATE NOT NULL,
    comensales    INTEGER DEFAULT 1,
    estado        VARCHAR(20) DEFAULT 'abierto',          -- 'abierto', 'pagado', 'anulado'
    propina       NUMERIC(10,2) DEFAULT 0,
    observaciones TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS detalle_pedido (
    id              SERIAL PRIMARY KEY,
    pedido_id       INTEGER NOT NULL REFERENCES pedidos(id),
    producto_id     INTEGER REFERENCES productos(id),
    cantidad        INTEGER DEFAULT 1,
    precio_unitario NUMERIC(10,2) NOT NULL,
    costo_unitario  NUMERIC(10,2) NOT NULL DEFAULT 0,
    total           NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    costo_total     NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * costo_unitario) STORED,
    margen          NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * (precio_unitario - costo_unitario)) STORED
);

CREATE TABLE IF NOT EXISTS pagos (
    id          SERIAL PRIMARY KEY,
    pedido_id   INTEGER NOT NULL REFERENCES pedidos(id),
    fecha       DATE NOT NULL,
    monto       NUMERIC(10,2) NOT NULL,
    metodo      VARCHAR(30),                  -- 'efectivo', 'tarjeta', 'transferencia'
    propina     NUMERIC(10,2) DEFAULT 0,
    estado      VARCHAR(20) DEFAULT 'pagado',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Índices
CREATE UNIQUE INDEX IF NOT EXISTS ux_productos_id_externo ON productos(id_externo) WHERE id_externo IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_pedidos_id_externo   ON pedidos(id_externo)   WHERE id_externo IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_pedidos_fecha        ON pedidos(fecha);
CREATE INDEX IF NOT EXISTS idx_pedidos_estado       ON pedidos(estado);
CREATE INDEX IF NOT EXISTS idx_pedidos_canal        ON pedidos(canal_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_mesa         ON pedidos(mesa_id);
CREATE INDEX IF NOT EXISTS idx_detalle_pedido       ON detalle_pedido(pedido_id);
CREATE INDEX IF NOT EXISTS idx_detalle_producto     ON detalle_pedido(producto_id);
CREATE INDEX IF NOT EXISTS idx_pagos_pedido         ON pagos(pedido_id);
CREATE INDEX IF NOT EXISTS idx_pagos_fecha          ON pagos(fecha);
