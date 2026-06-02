CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  phone TEXT UNIQUE NOT NULL,
  notification_phone TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  avatar_url TEXT,
  profile_embedding vector(512),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS price_watches (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  target TEXT NOT NULL,
  target_price NUMERIC(12, 2) NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('below', 'above', 'change')),
  check_interval_minutes INTEGER NOT NULL DEFAULT 60,
  current_price NUMERIC(12, 2),
  status TEXT NOT NULL DEFAULT 'idle',
  last_error TEXT,
  extraction_key TEXT,
  extraction_strategy TEXT,
  extraction_selector TEXT,
  extraction_label TEXT,
  extraction_confidence NUMERIC(5, 2),
  last_candidates JSONB NOT NULL DEFAULT '[]',
  last_checked_at TIMESTAMPTZ,
  next_check_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS price_history (
  id BIGSERIAL PRIMARY KEY,
  price_watch_id BIGINT NOT NULL REFERENCES price_watches(id) ON DELETE CASCADE,
  price NUMERIC(12, 2) NOT NULL,
  checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS store_watches (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  store_url TEXT NOT NULL,
  keywords TEXT,
  min_score NUMERIC(5, 2) NOT NULL DEFAULT 80,
  check_interval_minutes INTEGER NOT NULL DEFAULT 360,
  status TEXT NOT NULL DEFAULT 'idle',
  last_error TEXT,
  last_checked_at TIMESTAMPTZ,
  next_check_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS discovered_products (
  id BIGSERIAL PRIMARY KEY,
  store_watch_id BIGINT NOT NULL REFERENCES store_watches(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  image_url TEXT,
  price NUMERIC(12, 2),
  embedding vector(512),
  score NUMERIC(5, 2) NOT NULL DEFAULT 0,
  matched BOOLEAN NOT NULL DEFAULT false,
  discovered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (store_watch_id, url)
);

CREATE TABLE IF NOT EXISTS notification_events (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}',
  read BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_price_watches_next_check ON price_watches(next_check_at);
CREATE INDEX IF NOT EXISTS idx_store_watches_next_check ON store_watches(next_check_at);
CREATE INDEX IF NOT EXISTS idx_discovered_products_store ON discovered_products(store_watch_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notification_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_profile_embedding
  ON users USING ivfflat (profile_embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_products_embedding
  ON discovered_products USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
