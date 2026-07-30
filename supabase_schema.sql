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
  id SERIAL,
  source_channel TEXT NOT NULL,
  source_video_id TEXT NOT NULL,
  mirrored_video_id TEXT,
  original_title TEXT DEFAULT '',
  mirrored_at TIMESTAMPTZ,
  comment_id TEXT DEFAULT '',
  shortened_urls JSONB DEFAULT '{}',
  project_id TEXT NOT NULL DEFAULT '',
  UNIQUE(project_id, source_channel, source_video_id)
);

-- 5. Mirror stats (replaces state.json "stats")
CREATE TABLE IF NOT EXISTS mirror_stats (
  project_id TEXT NOT NULL DEFAULT '' PRIMARY KEY,
  total_mirrored INTEGER DEFAULT 0,
  total_comments INTEGER DEFAULT 0,
  total_shortened INTEGER DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Upload / warmup state (replaces upload_state.json)
CREATE TABLE IF NOT EXISTS upload_state (
  project_id TEXT NOT NULL DEFAULT '' PRIMARY KEY,
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
  warmup_days INTEGER DEFAULT 0,
  warmup_start TEXT DEFAULT '',
  comment_moderation TEXT DEFAULT 'heldForReview',
  mirror_title_prefix TEXT DEFAULT '',
  proxy_supabase_url TEXT DEFAULT '',
  proxy_supabase_key TEXT DEFAULT '',
  deployed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Migration: add proxy Supabase columns to projects
ALTER TABLE projects ADD COLUMN IF NOT EXISTS proxy_supabase_url TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS proxy_supabase_key TEXT DEFAULT '';

-- Migration: add upload scheduling columns
ALTER TABLE projects ADD COLUMN IF NOT EXISTS uploads_per_day INTEGER DEFAULT 2;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS initial_backfill INTEGER DEFAULT 5;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS upload_schedule TEXT DEFAULT '';

-- 9. Daily upload logs (replaces daily_log.json)
CREATE TABLE IF NOT EXISTS upload_logs (
  id SERIAL PRIMARY KEY,
  upload_date DATE NOT NULL,
  upload_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  video_id TEXT NOT NULL,
  title TEXT DEFAULT '',
  short_url TEXT DEFAULT '',
  comment_id TEXT DEFAULT '',
  project_id TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 10. Channel cursor — last checked video per channel (from monitor)
CREATE TABLE IF NOT EXISTS channel_cursors (
  project_id TEXT NOT NULL DEFAULT '',
  channel_id TEXT NOT NULL,
  last_video_id TEXT DEFAULT '',
  last_checked TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (project_id, channel_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_mirror_state_source ON mirror_state(project_id, source_channel, source_video_id);
CREATE INDEX IF NOT EXISTS idx_upload_logs_date ON upload_logs(project_id, upload_date DESC);
CREATE INDEX IF NOT EXISTS idx_upload_logs_time ON upload_logs(upload_time DESC);

-- ─── Migration: add project_id to existing tables ─────────────────────────
ALTER TABLE mirror_state ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';
ALTER TABLE mirror_stats ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';
ALTER TABLE upload_state ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';
ALTER TABLE upload_logs ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';
ALTER TABLE channel_cursors ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT '';

-- Update constraints for multi-project isolation
ALTER TABLE mirror_state DROP CONSTRAINT IF EXISTS mirror_state_source_channel_source_video_id_key;
ALTER TABLE mirror_state DROP CONSTRAINT IF EXISTS mirror_state_pid_source;
ALTER TABLE mirror_state ADD CONSTRAINT mirror_state_pid_source UNIQUE (project_id, source_channel, source_video_id);

ALTER TABLE channel_cursors DROP CONSTRAINT IF EXISTS channel_cursors_pkey;
ALTER TABLE channel_cursors ADD PRIMARY KEY (project_id, channel_id);

-- Handle upload_state and mirror_stats transitioning from id-based to project_id-based PK
-- Only needed if old-style tables (with id SERIAL) still exist
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='upload_state' AND column_name='id') THEN
    ALTER TABLE upload_state DROP CONSTRAINT IF EXISTS upload_state_pkey;
    ALTER TABLE upload_state ALTER COLUMN id DROP DEFAULT;
    ALTER TABLE upload_state DROP COLUMN IF EXISTS id;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='mirror_stats' AND column_name='id') THEN
    ALTER TABLE mirror_stats DROP CONSTRAINT IF EXISTS mirror_stats_pkey;
    ALTER TABLE mirror_stats ALTER COLUMN id DROP DEFAULT;
    ALTER TABLE mirror_stats DROP COLUMN IF EXISTS id;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='mirror_state' AND column_name='id') THEN
    ALTER TABLE mirror_state DROP COLUMN IF EXISTS id;
  END IF;
END$$;
-- Re-ensure PK on project_id for upload_state and mirror_stats
--
-- If the old table had id SERIAL PRIMARY KEY and the new CREATE TABLE IF NOT EXISTS
-- was skipped, project_id has no PK yet. Add it only if missing.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage ccu USING (constraint_name)
    WHERE tc.table_name='upload_state' AND tc.constraint_type='PRIMARY KEY'
      AND ccu.column_name='project_id') THEN
    ALTER TABLE upload_state ADD PRIMARY KEY (project_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints tc
    JOIN information_schema.constraint_column_usage ccu USING (constraint_name)
    WHERE tc.table_name='mirror_stats' AND tc.constraint_type='PRIMARY KEY'
      AND ccu.column_name='project_id') THEN
    ALTER TABLE mirror_stats ADD PRIMARY KEY (project_id);
  END IF;
END$$;
