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
    clase            VARCHAR(10) NOT NULL DEFAULT 'compra',    -- compra | venta (RCV del SII)
    numero_documento VARCHAR(50),
    rut_contraparte  VARCHAR(20),                              -- RUT proveedor (compra) / cliente (venta)
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

-- Dedup idempotente de cargas de RCV (un DTE = tipo+folio+RUT+clase).
CREATE UNIQUE INDEX IF NOT EXISTS ux_doc_rcv ON documentos_tributarios
    (clase, tipo, numero_documento, rut_contraparte)
    WHERE numero_documento IS NOT NULL AND rut_contraparte IS NOT NULL;

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

-- ── Marketing (HORIZONTAL: cualquier empresa puede tener una plataforma de ads) ──
CREATE TABLE IF NOT EXISTS canales_marketing (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(80) UNIQUE NOT NULL,   -- 'Meta', 'Google', ...
    tipo        VARCHAR(30) DEFAULT 'pagado',  -- 'pagado' | 'organico'
    plataforma  VARCHAR(40),                   -- 'meta', 'google'
    activo      BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS campanas (
    id                 SERIAL PRIMARY KEY,
    canal_id           INTEGER REFERENCES canales_marketing(id),
    id_externo         VARCHAR(64) UNIQUE,       -- id de la campaña en la plataforma
    nombre             VARCHAR(200) NOT NULL,
    objetivo           VARCHAR(80),              -- 'OUTCOME_LEADS', 'REACH', ...
    estado             VARCHAR(30),              -- 'ACTIVE', 'PAUSED', ...
    presupuesto_diario NUMERIC(14,2),
    fecha_inicio       DATE,
    fecha_fin          DATE,
    actualizado_en     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS insights_marketing (
    id             SERIAL PRIMARY KEY,
    campana_id     INTEGER NOT NULL REFERENCES campanas(id),
    fecha          DATE NOT NULL,
    gasto          NUMERIC(14,2) DEFAULT 0,
    impresiones    BIGINT DEFAULT 0,
    clics          BIGINT DEFAULT 0,
    alcance        BIGINT DEFAULT 0,
    conversiones   NUMERIC(14,2) DEFAULT 0,    -- acciones de conversión (ej. leads)
    mensajes       BIGINT DEFAULT 0,           -- conversaciones de mensajes iniciadas
    interacciones  BIGINT DEFAULT 0,           -- post/page engagement
    reproducciones BIGINT DEFAULT 0,           -- video views
    visitas_perfil BIGINT DEFAULT 0,           -- visitas al perfil (IG/FB)
    moneda         VARCHAR(8) DEFAULT 'CLP',
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (campana_id, fecha)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_insights_fecha       ON insights_marketing(fecha);
CREATE INDEX IF NOT EXISTS idx_campanas_canal       ON campanas(canal_id);
CREATE INDEX IF NOT EXISTS idx_gastos_fecha         ON gastos(fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_categoria     ON gastos(categoria_id);
CREATE INDEX IF NOT EXISTS idx_documentos_estado    ON documentos_tributarios(estado);
CREATE INDEX IF NOT EXISTS idx_documentos_fecha     ON documentos_tributarios(fecha);
CREATE INDEX IF NOT EXISTS idx_movbancarios_fecha   ON movimientos_bancarios(fecha);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp      ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_rol            ON audit_log(rol);
CREATE INDEX IF NOT EXISTS idx_audit_estado         ON audit_log(estado);
