-- ─────────────────────────────────────────────────────────────
-- Pack: base  (siempre activo)
--
-- Tablas comunes a toda empresa, independientes de su sistema de datos:
-- gastos, facturas (documentos tributarios), banco, presupuesto y auditoría.
-- Habilita: Gastos, Tributario, CxC/CxP (desde facturas), Tesorería,
-- Presupuesto, Conciliación.
--
-- Todos los CREATE son IF NOT EXISTS (idempotentes): aplicar el fragmento
-- sobre un schema existente no toca lo ya creado.
-- ─────────────────────────────────────────────────────────────

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

CREATE TABLE IF NOT EXISTS presupuesto (
    id        SERIAL PRIMARY KEY,
    anio      INTEGER       NOT NULL,
    mes       INTEGER       NOT NULL CHECK (mes BETWEEN 1 AND 12),
    tipo      VARCHAR(20)   NOT NULL DEFAULT 'gasto' CHECK (tipo IN ('ingreso', 'gasto')),
    categoria VARCHAR(100)  NOT NULL,
    monto     NUMERIC(12,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (anio, mes, tipo, categoria)
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
CREATE INDEX IF NOT EXISTS idx_gastos_fecha         ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_categoria     ON gastos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_documentos_estado    ON documentos_tributarios(estado);
CREATE INDEX IF NOT EXISTS idx_documentos_fecha     ON documentos_tributarios(fecha);
CREATE INDEX IF NOT EXISTS idx_movbancarios_fecha   ON movimientos_bancarios(fecha);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp      ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_rol            ON audit_log(rol);
CREATE INDEX IF NOT EXISTS idx_audit_estado         ON audit_log(estado);
