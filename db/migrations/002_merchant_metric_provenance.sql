ALTER TABLE merchants
  ADD COLUMN IF NOT EXISTS metrics_source_url text;
