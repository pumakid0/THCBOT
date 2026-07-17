-- THCBOT v1.0 — Schema completo
-- Ejecutar en Supabase → SQL Editor → New query

-- ── Extensiones ────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Tabla: users ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    tg_id        BIGINT       PRIMARY KEY,
    username     TEXT         NOT NULL DEFAULT '',
    first_name   TEXT         NOT NULL DEFAULT '',
    paymail      TEXT         NOT NULL DEFAULT '',
    bsv_addr     TEXT         NOT NULL DEFAULT '',
    bsv_balance  NUMERIC(20,8) NOT NULL DEFAULT 0,
    btc_balance  NUMERIC(20,8) NOT NULL DEFAULT 0,
    ltc_balance  NUMERIC(20,8) NOT NULL DEFAULT 0,
    mnee_balance NUMERIC(20,8) NOT NULL DEFAULT 0,
    eur_balance  NUMERIC(12,2) NOT NULL DEFAULT 0,
    is_active    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Tabla: transactions ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id          BIGSERIAL    PRIMARY KEY,
    sender_id   BIGINT       NOT NULL,
    receiver_id BIGINT       NOT NULL,
    amount      NUMERIC(20,8) NOT NULL DEFAULT 0,
    asset       TEXT         NOT NULL DEFAULT 'BSV',
    type        TEXT         NOT NULL DEFAULT 'TRANSFER',
    meta        JSONB        NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Tabla: paylinks ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS paylinks (
    id          TEXT         PRIMARY KEY,
    owner_id    BIGINT       NOT NULL,
    amount      NUMERIC(20,8) NOT NULL,
    asset       TEXT         NOT NULL DEFAULT 'BSV',
    description TEXT         NOT NULL DEFAULT '',
    paymail     TEXT         NOT NULL DEFAULT '',
    bsv_addr    TEXT         NOT NULL DEFAULT '',
    paid        BOOLEAN      NOT NULL DEFAULT FALSE,
    payer_id    BIGINT,
    expires_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Tabla: streams ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS streams (
    id           BIGSERIAL    PRIMARY KEY,
    sender_id    BIGINT       NOT NULL,
    receiver_id  BIGINT       NOT NULL,
    rate_per_sec NUMERIC(20,8) NOT NULL,
    asset        TEXT         NOT NULL DEFAULT 'BSV',
    active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_tick    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── Índices ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_tx_sender    ON transactions(sender_id);
CREATE INDEX IF NOT EXISTS idx_tx_receiver  ON transactions(receiver_id);
CREATE INDEX IF NOT EXISTS idx_tx_type      ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_tx_created   ON transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_tx_otp       ON transactions(type, created_at)
    WHERE type IN ('EXTENSION_OTP','EXTENSION_OTP_USED');
CREATE INDEX IF NOT EXISTS idx_streams_act  ON streams(active)
    WHERE active = TRUE;
CREATE INDEX IF NOT EXISTS idx_paylinks_own ON paylinks(owner_id);

-- ── Row Level Security (desactivar para bot server-side) ────────
ALTER TABLE users        DISABLE ROW LEVEL SECURITY;
ALTER TABLE transactions DISABLE ROW LEVEL SECURITY;
ALTER TABLE paylinks     DISABLE ROW LEVEL SECURITY;
ALTER TABLE streams      DISABLE ROW LEVEL SECURITY;

-- ── Bot owner (reemplaza TG_ID) ─────────────────────────────────
-- INSERT INTO users (tg_id, username, first_name, bsv_balance)
-- VALUES (TU_TG_ID, 'thcbot', 'THCBOT', 10.0)
-- ON CONFLICT (tg_id) DO NOTHING;

-- ── House account para fees/juegos (tg_id = -1) ─────────────────
INSERT INTO users (tg_id, username, first_name, bsv_balance)
VALUES (-1, 'house', 'House', 1.0)
ON CONFLICT (tg_id) DO NOTHING;
