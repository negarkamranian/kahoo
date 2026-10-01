CREATE INDEX IF NOT EXISTS idx_search_documents_embedding_hnsw
  ON search_documents USING hnsw (embedding vector_cosine_ops)
  WHERE embedding IS NOT NULL;
