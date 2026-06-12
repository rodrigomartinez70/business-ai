-- ─────────────────────────────────────────────────────────────
-- Pack: pos_hotelero  (PMS de hotel)
--
-- Habitaciones, huéspedes, reservas, cobros y consumos. Habilita las
-- fuentes de Ventas hoteleras (hospedaje, noches, consumos, ADR/RevPAR,
-- hospedaje_por_canal).
-- Idempotente (CREATE ... IF NOT EXISTS).
-- ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS habitaciones (
    id              SERIAL PRIMARY KEY,
    numero          VARCHAR(10) UNIQUE NOT NULL,
    tipo            VARCHAR(50),
    capacidad       INTEGER DEFAULT 2,
    tarifa_base     NUMERIC(10,2),
    activa          BOOLEAN DEFAULT TRUE,
    descripcion     TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS canales_venta (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    comision_pct    NUMERIC(5,2) DEFAULT 0,
    activo          BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS huespedes (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) NOT NULL,
    apellido        VARCHAR(100) NOT NULL,
    tipo_documento  VARCHAR(20),
    documento       VARCHAR(50),
    nacionalidad    VARCHAR(50),
    email           VARCHAR(100),
    telefono        VARCHAR(20),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reservas (
    id              SERIAL PRIMARY KEY,
    habitacion_id   INTEGER NOT NULL REFERENCES habitaciones(id),
    huesped_id      INTEGER NOT NULL REFERENCES huespedes(id),
    canal_id        INTEGER REFERENCES canales_venta(id),
    fecha_entrada   DATE NOT NULL,
    fecha_salida    DATE NOT NULL,
    noches          INTEGER GENERATED ALWAYS AS (fecha_salida - fecha_entrada) STORED,
    tarifa_noche    NUMERIC(10,2) NOT NULL,
    total_hospedaje NUMERIC(10,2) GENERATED ALWAYS AS ((fecha_salida - fecha_entrada) * tarifa_noche) STORED,
    estado          VARCHAR(20) DEFAULT 'confirmada',
    observaciones   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pagos (
    id              SERIAL PRIMARY KEY,
    reserva_id      INTEGER NOT NULL REFERENCES reservas(id),
    fecha           DATE NOT NULL,
    monto           NUMERIC(10,2) NOT NULL,
    metodo          VARCHAR(30),
    concepto        VARCHAR(100),
    estado          VARCHAR(20) DEFAULT 'pagado',
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS consumos_frigobar (
    id              SERIAL PRIMARY KEY,
    reserva_id      INTEGER NOT NULL REFERENCES reservas(id),
    fecha           DATE NOT NULL,
    descripcion     VARCHAR(100),
    cantidad        INTEGER DEFAULT 1,
    precio_unitario NUMERIC(10,2) NOT NULL,
    costo_unitario  NUMERIC(10,2) NOT NULL DEFAULT 0,
    total           NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    costo_total     NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * costo_unitario) STORED,
    margen          NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * (precio_unitario - costo_unitario)) STORED
);

CREATE TABLE IF NOT EXISTS consumos_servicios (
    id              SERIAL PRIMARY KEY,
    reserva_id      INTEGER NOT NULL REFERENCES reservas(id),
    fecha           DATE NOT NULL,
    servicio        VARCHAR(100) NOT NULL,
    descripcion     TEXT,
    cantidad        INTEGER DEFAULT 1,
    precio_unitario NUMERIC(10,2) NOT NULL,
    costo_unitario  NUMERIC(10,2) NOT NULL DEFAULT 0,
    total           NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * precio_unitario) STORED,
    costo_total     NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * costo_unitario) STORED,
    margen          NUMERIC(10,2) GENERATED ALWAYS AS (cantidad * (precio_unitario - costo_unitario)) STORED
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_reservas_fechas        ON reservas(fecha_entrada, fecha_salida);
CREATE INDEX IF NOT EXISTS idx_reservas_estado        ON reservas(estado);
CREATE INDEX IF NOT EXISTS idx_reservas_estado_salida ON reservas(estado, fecha_salida);
CREATE INDEX IF NOT EXISTS idx_reservas_habitacion    ON reservas(habitacion_id);
CREATE INDEX IF NOT EXISTS idx_reservas_huesped       ON reservas(huesped_id);
CREATE INDEX IF NOT EXISTS idx_pagos_reserva          ON pagos(reserva_id);
CREATE INDEX IF NOT EXISTS idx_pagos_fecha            ON pagos(fecha);
CREATE INDEX IF NOT EXISTS idx_consumos_reserva       ON consumos_frigobar(reserva_id);
CREATE INDEX IF NOT EXISTS idx_servicios_reserva      ON consumos_servicios(reserva_id);
CREATE INDEX IF NOT EXISTS idx_servicios_fecha        ON consumos_servicios(fecha);
