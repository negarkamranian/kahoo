ALTER TABLE merchants
  ADD COLUMN IF NOT EXISTS avatar_updated_at timestamptz;

UPDATE merchants
SET avatar_updated_at = COALESCE(avatar_updated_at, CURRENT_TIMESTAMP)
WHERE avatar_blob IS NOT NULL;
