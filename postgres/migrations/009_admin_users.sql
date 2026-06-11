-- 009_admin_users.sql — Usuarios del back-office MBI Admin (login con usuario+contraseña).
-- Se suman al admin bootstrap del entorno (ADMIN_USER/ADMIN_PASSWORD). password_hash:
-- PBKDF2-HMAC-SHA256 con salt (formato 'pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>').

CREATE TABLE IF NOT EXISTS public.admin_users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(60)  UNIQUE NOT NULL,
    password_hash TEXT         NOT NULL,
    activo        BOOLEAN      DEFAULT TRUE,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
