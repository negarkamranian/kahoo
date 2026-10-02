ALTER TABLE search_documents
  ADD COLUMN title_content text NOT NULL DEFAULT '',
  ADD COLUMN body_content text NOT NULL DEFAULT '',
  ADD COLUMN published_at timestamptz;

UPDATE search_documents SET body_content=content WHERE body_content='';

DROP INDEX IF EXISTS idx_search_documents_fts;
ALTER TABLE search_documents DROP COLUMN search_vector;
ALTER TABLE search_documents ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
  setweight(to_tsvector('simple', coalesce(title_content, '')), 'A') ||
  setweight(to_tsvector('simple', coalesce(body_content, '')), 'B')
) STORED;

CREATE INDEX idx_search_documents_fts
  ON search_documents USING gin(search_vector);
CREATE INDEX idx_search_documents_title_trgm
  ON search_documents USING gin(title_content gin_trgm_ops);
CREATE INDEX idx_search_documents_published
  ON search_documents(published_at DESC)
  WHERE published_at IS NOT NULL;
