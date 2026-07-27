-- YouTube Mirror Bot — state tracking tables
-- Run in Supabase SQL Editor if using remote state

CREATE TABLE IF NOT EXISTS mirror_state (
  id BIGSERIAL PRIMARY KEY,
  channel_id TEXT NOT NULL,
  video_id TEXT NOT NULL,
  new_video_id TEXT,
  original_title TEXT,
  mirrored_at TIMESTAMPTZ DEFAULT now(),
  comment_id TEXT,
  shortened_url TEXT,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'mirrored', 'failed', 'skipped')),
  error_msg TEXT,
  UNIQUE(channel_id, video_id)
);

CREATE INDEX IF NOT EXISTS idx_mirror_state_channel ON mirror_state (channel_id, mirrored_at DESC);
CREATE INDEX IF NOT EXISTS idx_mirror_state_status ON mirror_state (status);

CREATE TABLE IF NOT EXISTS mirror_channels (
  id BIGSERIAL PRIMARY KEY,
  channel_id TEXT UNIQUE NOT NULL,
  alias TEXT,
  url TEXT,
  enabled BOOLEAN DEFAULT true,
  added_at TIMESTAMPTZ DEFAULT now(),
  last_checked TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS mirror_stats (
  id BIGSERIAL PRIMARY KEY,
  date DATE DEFAULT CURRENT_DATE,
  mirrored_count INT DEFAULT 0,
  comments_count INT DEFAULT 0,
  shortened_count INT DEFAULT 0,
  errors_count INT DEFAULT 0,
  UNIQUE(date)
);
