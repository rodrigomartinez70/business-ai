-- ─────────────────────────────────────────────────────────────
-- Esquema de Marketing (HORIZONTAL)
--
-- Datos de plataformas publicitarias (Meta Ads, etc.), agnóstico al rubro.
-- Se aplica al schema de cada tenant (con search_path seteado al tenant).
-- Idempotente: usar IF NOT EXISTS, se puede correr más de una vez.
-- ─────────────────────────────────────────────────────────────

-- Canales / plataformas de marketing
CREATE TABLE IF NOT EXISTS canales_marketing (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(80) UNIQUE NOT NULL,   -- 'Meta', 'Google', ...
    tipo        VARCHAR(30) DEFAULT 'pagado',  -- 'pagado' | 'organico'
    plataforma  VARCHAR(40),                   -- 'meta', 'google'
    activo      BOOLEAN DEFAULT TRUE
);

-- Campañas (espejo de las campañas de la plataforma)
CREATE TABLE IF NOT EXISTS campanas (
    id                 SERIAL PRIMARY KEY,
    canal_id           INTEGER REFERENCES canales_marketing(id),
    id_externo         VARCHAR(64) UNIQUE,       -- id de la campaña en la plataforma (Meta)
    nombre             VARCHAR(200) NOT NULL,
    objetivo           VARCHAR(80),              -- 'OUTCOME_LEADS', 'REACH', ...
    estado             VARCHAR(30),              -- 'ACTIVE', 'PAUSED', ...
    presupuesto_diario NUMERIC(14,2),
    fecha_inicio       DATE,
    fecha_fin          DATE,
    actualizado_en     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Métricas diarias por campaña (grano: campaña × día → upsert idempotente)
CREATE TABLE IF NOT EXISTS insights_marketing (
    id             SERIAL PRIMARY KEY,
    campana_id     INTEGER NOT NULL REFERENCES campanas(id),
    fecha          DATE NOT NULL,
    gasto          NUMERIC(14,2) DEFAULT 0,
    impresiones    BIGINT DEFAULT 0,
    clics          BIGINT DEFAULT 0,
    alcance        BIGINT DEFAULT 0,
    conversiones   NUMERIC(14,2) DEFAULT 0,    -- acciones de conversión (ej. leads)
    moneda         VARCHAR(8) DEFAULT 'CLP',
    actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (campana_id, fecha)
);

CREATE INDEX IF NOT EXISTS idx_insights_fecha   ON insights_marketing(fecha);
CREATE INDEX IF NOT EXISTS idx_campanas_canal   ON campanas(canal_id);
