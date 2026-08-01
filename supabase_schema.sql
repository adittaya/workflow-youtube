-- ============================================================================
-- YT VIDEO AUTOMATION — Supabase Schema
-- Run this in your Supabase project SQL editor (https://supabase.com/dashboard)
-- ============================================================================
-- Manual upload tool: projects, accounts, upload state/logs, verify + alerts.
-- The 24/7 tables (channels, channel_cursors, mirror_state, mirror_stats,
-- work_queue, run_locks) and the github/channel/warmup/schedule/proxy columns
-- are retired and dropped below.

-- 1. Settings (key-value store, replaces settings.json)
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL DEFAULT '{}',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. OAuth accounts (replaces accounts.json) — every saved YouTube account,
-- with its own credentials, channel identity, health and usage tracking.
CREATE TABLE IF NOT EXISTS accounts (
  name TEXT PRIMARY KEY,
  client_id TEXT NOT NULL DEFAULT '',
  client_secret TEXT NOT NULL DEFAULT '',
  refresh_token TEXT NOT NULL DEFAULT '',
  access_token TEXT DEFAULT '',
  email TEXT DEFAULT '',
  channel_id TEXT DEFAULT '',
  channel_name TEXT DEFAULT '',
  channel_url TEXT DEFAULT '',
  avatar_url TEXT DEFAULT '',
  status TEXT DEFAULT 'active',
  last_verified TIMESTAMPTZ,
  last_error TEXT DEFAULT '',
  token_expires_at TIMESTAMPTZ,
  uploads_count BIGINT DEFAULT 0,
  notes TEXT DEFAULT '',
  added_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS access_token TEXT DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS email TEXT DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS channel_url TEXT DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS avatar_url TEXT DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_verified TIMESTAMPTZ;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS last_error TEXT DEFAULT '';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS token_expires_at TIMESTAMPTZ;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS uploads_count BIGINT DEFAULT 0;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS notes TEXT DEFAULT '';

-- 3. Upload state (replaces upload_state.json)
CREATE TABLE IF NOT EXISTS upload_state (
  project_id TEXT NOT NULL DEFAULT '' PRIMARY KEY,
  account_created TIMESTAMPTZ,
  first_upload_date DATE,
  total_uploaded INTEGER DEFAULT 0,
  last_upload_date DATE,
  last_upload_hour TIMESTAMPTZ,
  processed_hashes TEXT[] DEFAULT '{}',
  yt_client_id TEXT DEFAULT '',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE upload_state DROP COLUMN IF EXISTS warmup_start;
ALTER TABLE upload_state DROP COLUMN IF EXISTS warmup_complete;
ALTER TABLE upload_state DROP COLUMN IF EXISTS filled_slots;
ALTER TABLE upload_state DROP COLUMN IF EXISTS filled_slots_date;

-- 4. Projects — multi-project management (all credentials per project, no local files)
CREATE TABLE IF NOT EXISTS projects (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  yt_client_id TEXT DEFAULT '',
  yt_client_secret TEXT DEFAULT '',
  yt_refresh_token TEXT DEFAULT '',
  account_id TEXT DEFAULT '',
  shortlink_provider TEXT DEFAULT 'vplink',
  shortlink_api_key TEXT DEFAULT '',
  comment_moderation TEXT DEFAULT 'heldForReview',
  mirror_title_prefix TEXT DEFAULT '',
  mirror_description_suffix TEXT DEFAULT '',
  custom_title TEXT DEFAULT '',
  custom_description TEXT DEFAULT '',
  custom_comment TEXT DEFAULT '',
  privacy_status TEXT DEFAULT 'public',
  category_id TEXT DEFAULT '22',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Migration: add columns added after the original deploy
ALTER TABLE projects ADD COLUMN IF NOT EXISTS account_id TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS mirror_description_suffix TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS custom_title TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS custom_description TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS custom_comment TEXT DEFAULT '';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS privacy_status TEXT DEFAULT 'public';
ALTER TABLE projects ADD COLUMN IF NOT EXISTS category_id TEXT DEFAULT '22';

-- Drop retired project columns
ALTER TABLE projects DROP COLUMN IF EXISTS github_token;
ALTER TABLE projects DROP COLUMN IF EXISTS github_repo;
ALTER TABLE projects DROP COLUMN IF EXISTS channels;
ALTER TABLE projects DROP COLUMN IF EXISTS warmup_days;
ALTER TABLE projects DROP COLUMN IF EXISTS warmup_start;
ALTER TABLE projects DROP COLUMN IF EXISTS deployed_at;
ALTER TABLE projects DROP COLUMN IF EXISTS uploads_per_day;
ALTER TABLE projects DROP COLUMN IF EXISTS initial_backfill;
ALTER TABLE projects DROP COLUMN IF EXISTS upload_schedule;
ALTER TABLE projects DROP COLUMN IF EXISTS proxy_supabase_url;
ALTER TABLE projects DROP COLUMN IF EXISTS proxy_supabase_key;
ALTER TABLE projects DROP COLUMN IF EXISTS proxy_enabled;

-- 5. Daily upload logs (replaces daily_log.json)
CREATE TABLE IF NOT EXISTS upload_logs (
  id SERIAL PRIMARY KEY,
  upload_date DATE NOT NULL,
  upload_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  video_id TEXT NOT NULL,
  title TEXT DEFAULT '',
  short_url TEXT DEFAULT '',
  comment_id TEXT DEFAULT '',
  source_video_id TEXT DEFAULT '',
  source_channel TEXT DEFAULT '',
  project_id TEXT DEFAULT '',
  account_name TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE upload_logs ADD COLUMN IF NOT EXISTS account_name TEXT DEFAULT '';
ALTER TABLE upload_logs ADD COLUMN IF NOT EXISTS source_video_id TEXT DEFAULT '';
ALTER TABLE upload_logs ADD COLUMN IF NOT EXISTS source_channel TEXT DEFAULT '';

-- 6. Verify checks — latest result of every self-check, per project
CREATE TABLE IF NOT EXISTS verify_checks (
  project_id TEXT NOT NULL DEFAULT '',
  check_name TEXT NOT NULL,
  status TEXT DEFAULT 'ok',
  message TEXT DEFAULT '',
  details JSONB DEFAULT '{}',
  checked_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (project_id, check_name)
);

-- 7. Alerts — recurring issues, unresolved until fixed
CREATE TABLE IF NOT EXISTS alerts (
  id BIGSERIAL PRIMARY KEY,
  project_id TEXT NOT NULL DEFAULT '',
  severity TEXT DEFAULT 'warn',
  check_name TEXT DEFAULT '',
  message TEXT DEFAULT '',
  details JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  resolved_at TIMESTAMPTZ,
  resolved_by TEXT DEFAULT ''
);

-- ─── Retired 24/7 tables ────────────────────────────────────────────────────
DROP TABLE IF EXISTS channel_cursors;
DROP TABLE IF EXISTS channels;
DROP TABLE IF EXISTS mirror_state;
DROP TABLE IF EXISTS mirror_stats;
DROP TABLE IF EXISTS work_queue;
DROP TABLE IF EXISTS run_locks;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_upload_logs_date ON upload_logs(project_id, upload_date DESC);
CREATE INDEX IF NOT EXISTS idx_upload_logs_time ON upload_logs(upload_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts(project_id, resolved_at);
