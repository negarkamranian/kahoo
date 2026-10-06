CREATE TABLE saved_merchants (
  owner_id bigint NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (owner_id, merchant_id)
);

-- Keep a canonical thumbnail when a saved collection leaves the refreshed gallery.
-- These records never reference the volatile merchant_posts row identifiers.
CREATE TABLE saved_post_snapshots (
  merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  collection_key text NOT NULL CHECK (collection_key <> ''),
  permalink text NOT NULL,
  image_url text NOT NULL,
  image_blob bytea,
  mime_type text,
  image_count integer NOT NULL CHECK (image_count > 0),
  PRIMARY KEY (merchant_id, collection_key)
);

CREATE TABLE saved_posts (
  owner_id bigint NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  merchant_id bigint NOT NULL,
  collection_key text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (owner_id, merchant_id, collection_key),
  FOREIGN KEY (merchant_id, collection_key)
    REFERENCES saved_post_snapshots(merchant_id, collection_key) ON DELETE CASCADE
);

CREATE INDEX idx_saved_merchants_merchant ON saved_merchants(merchant_id);
CREATE INDEX idx_saved_posts_collection ON saved_posts(merchant_id, collection_key);
