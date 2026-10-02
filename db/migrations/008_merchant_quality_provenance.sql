ALTER TABLE merchants
  ADD COLUMN IF NOT EXISTS directory_quality_score double precision,
  ADD COLUMN IF NOT EXISTS directory_review_count integer,
  ADD COLUMN IF NOT EXISTS quality_source text,
  ADD COLUMN IF NOT EXISTS quality_source_url text,
  ADD COLUMN IF NOT EXISTS quality_updated_at timestamptz;

ALTER TABLE merchants
  DROP CONSTRAINT IF EXISTS merchants_directory_quality_score_check;

ALTER TABLE merchants
  ADD CONSTRAINT merchants_directory_quality_score_check
  CHECK (directory_quality_score IS NULL OR directory_quality_score BETWEEN 0 AND 5);
