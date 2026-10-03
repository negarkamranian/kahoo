-- Preserve the old per-row identity once, then require an explicit key on new rows.
UPDATE merchant_posts SET collection_key=id::text
WHERE collection_key IS NULL OR collection_key='';
ALTER TABLE merchant_posts ALTER COLUMN collection_key SET NOT NULL;
ALTER TABLE merchant_posts ADD CONSTRAINT merchant_posts_collection_key_nonempty
CHECK (collection_key <> '');
