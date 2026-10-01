ALTER TABLE merchants
  ADD COLUMN IF NOT EXISTS instagram_media_sync_version integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS instagram_media_synced_at timestamptz;
