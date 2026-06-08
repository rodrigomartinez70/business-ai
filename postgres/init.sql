-- ─────────────────────────────────────────────────────────────
-- Schema principal — Plataforma IA de Análisis de Negocio
-- ─────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────────────────────
-- TABLAS
-- ─────────────────────────────────────────────────────────────

CREATE TABLE habitaciones (
    id              SERIAL PRIMARY KEY,
    numero          VARCHAR(10) UNIQUE NOT NULL,  -- '101', '202', 'Suite1'
    tipo            VARCHAR(50),                  -- 'Simple', 'Doble', 'Suite'
    capacidad       INTEGER DEFAULT 2,
    tarifa_base     NUMERIC(10,2),                -- tarifa rack por noche
    activa          BOOLEAN DEFAULT TRUE,
    descripcion     TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE canales_venta (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,         -- 'Booking.com', 'Airbnb', 'Directo', 'Agencia'
    comision_pct    NUMERIC(5,2) DEFAULT 0,        -- % de comisión
    activo          BOOLEAN DEFAULT TRUE
);

CREATE TABLE huespedes (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    apellido        VARCHAR(100) NOT NULL,
    tipo_documento  VARCHAR(20),                   -- 'Pasaporte', 'DNI', 'RUT'
    documento       VARCHAR(50),
    nacionalidad    VARCHAR(50),
    email           VARCHAR(100),
    telefono        VARCHAR(20),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reservas (
    id              SERIAL PRIMARY KEY,
    habitacion_id   INTEGER NOT NULL REFERENCES habitaciones(id),
    huesped_id      INTEGER NOT NULL REFERENCES huespedes(id),
    canal_id        INTEGER REFERENCES canales_venta(id),
    fecha_entrada   DATE NOT NULL,
    fecha_salida    DATE NOT NULL,
    noches          INTEGER GENERATED ALWAYS AS (fecha_salida - fecha_entrada) STORED,
    tarifa_noche    NUMERIC(10,2) NOT NULL,
    total_hospedaje NUMERIC(10,2) GENERATED ALWAYS AS ((fecha_salida - fecha_entrada) * tarifa_noche) STORED,
    estado          VARCHAR(20) DEFAULT 'confirmada', -- 'confirmada', 'checkin', 'checkout', 'cancelada', 'no_show'
    observaciones   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE pagos (
    id              SERIAL PRIMARY KEY,
    reserva_id      INTEGER NOT NULL REFERENCES reservas(id),
    fecha           DATE NOT NULL,
    monto           NUMERIC(10,2) NOT NULL,
    metodo          VARCHAR(30),                   -- 'efectivo', 'tarjeta', 'transferencia'
    concepto        VARCHAR(100),                  -- 'hospedaje', 'frigobar', 'anticipo'
    estado          VARCHAR(20) DEFAULT 'pagado',  -- 'pagado', 'pendiente', 'anulado'
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE categorias_gasto (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,         -- 'Personal', 'Mantenimiento', 'Suministros', 'Marketing', 'Servicios'
    descripcion     TEXT
);

CREATE TABLE gastos (
    id              SERIAL PRIMARY KEY,
    categoria_id    INTEGER REFERENCES categorias_gasto(id),
    fecha           DATE NOT NULL,
    descripcion     TEXT NOT NULL,
    monto           NUMERIC(10,2) NOT NULL,
    proveedor       VARCHAR(100),
    comprobante     VARCHAR(50),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE documentos_tributarios (
    id              SERIAL PRIMARY KEY,
    fecha           DATE NOT NULL,
    tipo            VARCHAR(30) NOT NULL DEFAULT 'factura',  -- 'factura', 'boleta', 'nota_credito', 'factura_exenta'
    numero_documento VARCHAR(50),
    proveedor       VARCHAR(100) NOT NULL,
    monto_neto      NUMERIC(10,2) NOT NULL,
    monto_iva       NUMERIC(10,2),
    monto_total     NUMERIC(10,2),
    estado          VARCHAR(30) DEFAULT 'pendiente_revision', -- 'pendiente_revision', 'registrado', 'rechazado'
    categoria_gasto VARCHAR(100),
    observaciones   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE movimientos_bancarios (
    id              SERIAL PRIMARY KEY,
    fecha           DATE NOT NULL,
    glosa           TEXT,                              -- descripción del movimiento en la cartola
    monto           NUMERIC(12,2) NOT NULL,            -- signo: + abono (ingreso), - cargo (egreso)
    referencia      VARCHAR(100),                      -- nº operación/documento si la cartola lo trae
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE consumos_frigobar (
    id              SERIAL PRIMARY KEY,
    reserva_id      INTEGER NOT NULL REFERENCES reservas(id),
    fecha           DATE NOT NULL,
    descripcion     VARCHAR(100),                  -- 'Agua mineral', 'Cerveza', 'Snack'
    cantidad        INTEGER DEFAULT 1,
    precio_unitario NUMERIC(10,2) NOT NULL,
    costo_unitario  NUMERIC(10,2) NOT NULL DEFAULT 0,
    total           NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    costo_total     NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * costo_unitario) STORED,
    margen          NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * (precio_unitario - costo_unitario)) STORED
);

CREATE TABLE consumos_servicios (
    id              SERIAL PRIMARY KEY,
    reserva_id      INTEGER NOT NULL REFERENCES reservas(id),
    fecha           DATE NOT NULL,
    servicio        VARCHAR(100) NOT NULL,          -- 'Lavandería', 'Estacionamiento', 'Traslado'
    descripcion     TEXT,
    cantidad        INTEGER DEFAULT 1,
    precio_unitario NUMERIC(10,2) NOT NULL,
    costo_unitario  NUMERIC(10,2) NOT NULL DEFAULT 0,
    total           NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    costo_total     NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * costo_unitario) STORED,
    margen          NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * (precio_unitario - costo_unitario)) STORED
);

CREATE TABLE presupuesto (
    id        SERIAL PRIMARY KEY,
    anio      INTEGER       NOT NULL,
    mes       INTEGER       NOT NULL CHECK (mes BETWEEN 1 AND 12),
    tipo      VARCHAR(20)   NOT NULL DEFAULT 'gasto' CHECK (tipo IN ('ingreso', 'gasto')),
    categoria VARCHAR(100)  NOT NULL,                  -- 'ingresos' o nombre de categoría de gasto
    monto     NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (anio, mes, tipo, categoria)
);

CREATE TABLE audit_log (
    id              SERIAL PRIMARY KEY,
    rol             VARCHAR(50),
    pregunta        TEXT,
    sql_generado    TEXT,
    filas_retorn    INTEGER,
    duracion_ms     INTEGER,                           -- tiempo total de respuesta en ms
    estado          VARCHAR(20) DEFAULT 'ok',          -- 'ok' / 'error'
    tipo_flujo      VARCHAR(20),                       -- 'simple' / 'plan'
    modelo_llm      VARCHAR(50),                       -- 'claude' / 'ollama' / 'claude+ollama'
    error_msg       TEXT,                              -- detalle si estado='error'
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────────────────────
-- ROL DE APLICACIÓN
-- ─────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'negocio_user') THEN
        -- Contraseña debe coincidir con NEGOCIO_USER_PASSWORD en .env
        CREATE ROLE negocio_user LOGIN PASSWORD 'negocio_password_change_me';
    END IF;
END
$$;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO negocio_user', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO negocio_user;
GRANT SELECT ON habitaciones, canales_venta, huespedes, reservas, pagos, categorias_gasto, gastos, consumos_frigobar, consumos_servicios, documentos_tributarios, movimientos_bancarios, presupuesto TO negocio_user;
GRANT INSERT ON audit_log TO negocio_user;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq TO negocio_user;

-- ─────────────────────────────────────────────────────────────
-- ROL DE INGEST (INSERT en tablas de negocio, nunca el agente IA)
-- Contraseña debe coincidir con NEGOCIO_INGEST_PASSWORD en .env
-- ─────────────────────────────────────────────────────────────

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'negocio_ingest') THEN
        CREATE ROLE negocio_ingest LOGIN PASSWORD 'ingest_password_change_me';
    END IF;
END
$$;

DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO negocio_ingest', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO negocio_ingest;
GRANT SELECT, INSERT ON habitaciones, canales_venta, huespedes, reservas, pagos, categorias_gasto, gastos, consumos_frigobar, consumos_servicios, documentos_tributarios, movimientos_bancarios, presupuesto TO negocio_ingest;
GRANT INSERT ON audit_log TO negocio_ingest;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO negocio_ingest;

-- ─────────────────────────────────────────────────────────────
-- ÍNDICES
-- ─────────────────────────────────────────────────────────────

CREATE INDEX idx_reservas_fechas        ON reservas(fecha_entrada, fecha_salida);
CREATE INDEX idx_reservas_estado        ON reservas(estado);
CREATE INDEX idx_reservas_estado_salida ON reservas(estado, fecha_salida);  -- agentes financieros
CREATE INDEX idx_reservas_habitacion    ON reservas(habitacion_id);
CREATE INDEX idx_reservas_huesped       ON reservas(huesped_id);
CREATE INDEX idx_pagos_reserva          ON pagos(reserva_id);
CREATE INDEX idx_pagos_fecha            ON pagos(fecha);
CREATE INDEX idx_gastos_fecha           ON gastos(fecha);
CREATE INDEX idx_gastos_categoria       ON gastos(categoria_id);
CREATE INDEX idx_documentos_estado      ON documentos_tributarios(estado);
CREATE INDEX idx_documentos_fecha       ON documentos_tributarios(fecha);
CREATE INDEX idx_movbancarios_fecha     ON movimientos_bancarios(fecha);
CREATE INDEX idx_consumos_reserva       ON consumos_frigobar(reserva_id);
CREATE INDEX idx_servicios_reserva      ON consumos_servicios(reserva_id);
CREATE INDEX idx_servicios_fecha        ON consumos_servicios(fecha);
CREATE INDEX idx_audit_timestamp        ON audit_log(timestamp);
CREATE INDEX idx_audit_rol              ON audit_log(rol);
CREATE INDEX idx_audit_estado           ON audit_log(estado);
