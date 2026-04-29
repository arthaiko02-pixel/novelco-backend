-- ARLEELINES SQL Schema for Supabase
-- Run: Supabase > SQL Editor > New query

CREATE TABLE IF NOT EXISTS users (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name          TEXT NOT NULL,
    phone         TEXT DEFAULT '',
    company       TEXT DEFAULT '',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS news (
    id                  SERIAL PRIMARY KEY,
    telegram_message_id BIGINT UNIQUE,
    title               TEXT,
    content             TEXT NOT NULL,
    image_url           TEXT DEFAULT '',
    published_at        TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email);
CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at DESC);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE news  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "news_public_read"  ON news  FOR SELECT TO anon, authenticated USING (true);
CREATE POLICY "users_own_read"    ON users FOR SELECT TO authenticated
    USING (id::text = auth.uid()::text);
CREATE POLICY "users_service_all" ON users FOR ALL TO service_role USING (true);
CREATE POLICY "news_service_all"  ON news  FOR ALL TO service_role USING (true);
