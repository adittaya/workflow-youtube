-- ============================================================================
-- YouTube Mirror Bot — Supabase Schema
-- Run this in your Supabase project SQL editor (https://supabase.com/dashboard)
-- ============================================================================

-- 1. Settings (key-value store, replaces settings.json)
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. OAuth accounts (replaces accounts.json)
CREATE TABLE IF NOT EXISTS accounts (
  name TEXT PRIMARY KEY,
  client_id TEXT NOT NULL,
  client_secret TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  channel_id TEXT DEFAULT '',
  channel_name TEXT DEFAULT '',
  added_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Tracked channels (replaces channels.json)
CREATE TABLE IF NOT EXISTS channels (
  id TEXT PRIMARY KEY,
  name TEXT DEFAULT '',
  url TEXT DEFAULT '',
  enabled BOOLEAN DEFAULT true,
  added_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Mirror state — processed videos (replaces state.json "processed")
CREATE TABLE IF NOT EXISTS mirror_state (
  id SERIAL PRIMARY KEY,
  source_channel TEXT NOT NULL,
  source_video_id TEXT NOT NULL,
  mirrored_video_id TEXT,
  original_title TEXT DEFAULT '',
  mirrored_at TIMESTAMPTZ,
  comment_id TEXT DEFAULT '',
  shortened_urls JSONB DEFAULT '{}',
  UNIQUE(source_channel, source_video_id)
);

-- 5. Mirror stats (replaces state.json "stats")
CREATE TABLE IF NOT EXISTS mirror_stats (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  total_mirrored INTEGER DEFAULT 0,
  total_comments INTEGER DEFAULT 0,
  total_shortened INTEGER DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default stats row
INSERT INTO mirror_stats (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- 6. Upload / warmup state (replaces upload_state.json)
CREATE TABLE IF NOT EXISTS upload_state (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  account_created TIMESTAMPTZ,
  warmup_start TIMESTAMPTZ,
  warmup_complete BOOLEAN DEFAULT false,
  first_upload_date DATE,
  total_uploaded INTEGER DEFAULT 0,
  last_upload_date DATE,
  last_upload_hour TIMESTAMPTZ,
  processed_hashes TEXT[] DEFAULT '{}',
  yt_client_id TEXT DEFAULT '',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default upload_state row
INSERT INTO upload_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- 7. Projects — multi-project management (all credentials per project, no local files)
CREATE TABLE IF NOT EXISTS projects (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  yt_client_id TEXT DEFAULT '',
  yt_client_secret TEXT DEFAULT '',
  yt_refresh_token TEXT DEFAULT '',
  github_token TEXT DEFAULT '',
  github_repo TEXT DEFAULT '',
  channels TEXT DEFAULT '',
  shortlink_provider TEXT DEFAULT 'vplink',
  shortlink_api_key TEXT DEFAULT '',
  warmup_days INTEGER DEFAULT 14,
  warmup_start TEXT DEFAULT '',
  comment_moderation TEXT DEFAULT 'heldForReview',
  mirror_title_prefix TEXT DEFAULT '',
  deployed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 9. Daily upload logs (replaces daily_log.json)
CREATE TABLE IF NOT EXISTS upload_logs (
  id SERIAL PRIMARY KEY,
  upload_date DATE NOT NULL,
  upload_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  video_id TEXT NOT NULL,
  title TEXT DEFAULT '',
  short_url TEXT DEFAULT '',
  comment_id TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 10. Channel cursor — last checked video per channel (from monitor)
CREATE TABLE IF NOT EXISTS channel_cursors (
  channel_id TEXT PRIMARY KEY,
  last_video_id TEXT DEFAULT '',
  last_checked TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_mirror_state_source ON mirror_state(source_channel, source_video_id);
CREATE INDEX IF NOT EXISTS idx_upload_logs_date ON upload_logs(upload_date DESC);
CREATE INDEX IF NOT EXISTS idx_upload_logs_time ON upload_logs(upload_time DESC);
