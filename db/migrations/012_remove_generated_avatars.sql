UPDATE merchants
SET avatar_blob = NULL,
    avatar_mime_type = NULL,
    avatar_source_url = NULL,
    avatar_updated_at = NULL
WHERE avatar_mime_type = 'image/svg+xml'
  AND avatar_source_url IS NULL;

ALTER TABLE merchants DROP COLUMN avatar_initial, DROP COLUMN avatar_color;
