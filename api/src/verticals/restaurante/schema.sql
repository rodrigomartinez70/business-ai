-- ─────────────────────────────────────────────────────────────
-- Schema del vertical Restaurante
--
-- Template usado por scripts/provision_tenant.py para crear el
-- schema de un tenant nuevo. Se ejecuta con search_path seteado
-- al schema del tenant (ej. SET search_path = restaurante_xyz).
-- Los GRANT los maneja provision_tenant.py.
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

CREATE TABLE IF NOT EXISTS categorias_gasto (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL,
    descripcion TEXT
);

CREATE TABLE IF NOT EXISTS gastos (
    id           SERIAL PRIMARY KEY,
    categoria_id INTEGER REFERENCES categorias_gasto(id),
    fecha        DATE NOT NULL,
    descripcion  TEXT NOT NULL,
    monto        NUMERIC(10,2) NOT NULL,
    proveedor    VARCHAR(100),
    comprobante  VARCHAR(50),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documentos_tributarios (
    id               SERIAL PRIMARY KEY,
    fecha            DATE NOT NULL,
    tipo             VARCHAR(30) NOT NULL DEFAULT 'factura',
    numero_documento VARCHAR(50),
    proveedor        VARCHAR(100) NOT NULL,
    monto_neto       NUMERIC(10,2) NOT NULL,
    monto_iva        NUMERIC(10,2),
    monto_total      NUMERIC(10,2),
    estado           VARCHAR(30) DEFAULT 'pendiente_revision',
    categoria_gasto  VARCHAR(100),
    observaciones    TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movimientos_bancarios (
    id          SERIAL PRIMARY KEY,
    fecha       DATE NOT NULL,
    glosa       TEXT,
    monto       NUMERIC(12,2) NOT NULL,       -- signo: + abono (ingreso), - cargo (egreso)
    referencia  VARCHAR(100),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           SERIAL PRIMARY KEY,
    rol          VARCHAR(50),
    pregunta     TEXT,
    sql_generado TEXT,
    filas_retorn INTEGER,
    duracion_ms  INTEGER,
    estado       VARCHAR(20) DEFAULT 'ok',
    tipo_flujo   VARCHAR(20),
    modelo_llm   VARCHAR(50),
    error_msg    TEXT,
    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
CREATE INDEX IF NOT EXISTS idx_gastos_fecha         ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_categoria     ON gastos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_documentos_estado    ON documentos_tributarios(estado);
CREATE INDEX IF NOT EXISTS idx_documentos_fecha     ON documentos_tributarios(fecha);
CREATE INDEX IF NOT EXISTS idx_movbancarios_fecha   ON movimientos_bancarios(fecha);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp      ON audit_log(timestamp);
