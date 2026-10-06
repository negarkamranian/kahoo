-- Enrichment research is retained independently of volatile imported descriptions.
CREATE TABLE merchant_enrichment_history (
  id bigserial PRIMARY KEY,
  merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  researched_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  previous_description text NOT NULL,
  previous_provenance jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_merchant_enrichment_history_latest
  ON merchant_enrichment_history(merchant_id,id DESC);
