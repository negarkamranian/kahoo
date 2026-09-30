CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE categories (
  code text PRIMARY KEY,
  parent_code text REFERENCES categories(code),
  level smallint NOT NULL CHECK (level BETWEEN 1 AND 4),
  label_fa text NOT NULL,
  label_en text NOT NULL,
  icon text,
  sort_order integer NOT NULL DEFAULT 0
);

CREATE TABLE category_metadata (
  key text PRIMARY KEY,
  value text NOT NULL
);

CREATE TABLE merchants (
  id bigserial PRIMARY KEY,
  instagram_id text UNIQUE,
  name text NOT NULL,
  handle text NOT NULL UNIQUE,
  description text NOT NULL DEFAULT '',
  description_source text,
  description_source_url text,
  description_generated_by text,
  description_updated_at timestamptz,
  source_url text,
  biography text NOT NULL DEFAULT '',
  biography_source text,
  biography_updated_at timestamptz,
  category_code text NOT NULL REFERENCES categories(code),
  city text NOT NULL,
  avatar_initial text NOT NULL,
  avatar_color text NOT NULL,
  avatar_blob bytea,
  avatar_mime_type text,
  avatar_source_url text,
  instagram_url text NOT NULL,
  updated_label text NOT NULL,
  verified smallint NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
  verification_source text,
  verified_at timestamptz,
  followers_count bigint,
  following_count bigint,
  media_count bigint,
  former_username_count integer,
  account_created_at timestamptz,
  metrics_source text,
  metrics_updated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE merchant_posts (
  id bigserial PRIMARY KEY,
  merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  instagram_media_id text,
  caption text NOT NULL DEFAULT '',
  image_url text NOT NULL,
  image_blob bytea,
  mime_type text,
  permalink text NOT NULL,
  position smallint NOT NULL CHECK (position BETWEEN 1 AND 99),
  collection_key text,
  media_position smallint NOT NULL DEFAULT 1,
  published_at timestamptz,
  UNIQUE (merchant_id, position)
);

CREATE TABLE merchant_categories (
  merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  category_code text NOT NULL REFERENCES categories(code),
  confidence double precision NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
  source text NOT NULL,
  source_url text,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (merchant_id, category_code)
);

CREATE TABLE merchant_search_terms (
  id bigserial PRIMARY KEY,
  merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  term text NOT NULL,
  normalized_term text NOT NULL,
  weight double precision NOT NULL DEFAULT 1,
  source text NOT NULL,
  source_url text,
  generated_by text,
  confidence double precision NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 0 AND 1),
  updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (merchant_id, normalized_term, source)
);

CREATE TABLE search_aliases (
  alias text NOT NULL,
  normalized_alias text NOT NULL,
  term text NOT NULL,
  normalized_term text NOT NULL,
  weight double precision NOT NULL DEFAULT 0.5,
  source text NOT NULL,
  PRIMARY KEY (normalized_alias, normalized_term)
);

CREATE TABLE analytics_events (
  id bigserial PRIMARY KEY,
  event_type text NOT NULL CHECK (event_type IN (
    'search', 'category_view', 'merchant_click',
    'login_started', 'login_completed',
    'oauth_started', 'oauth_completed'
  )),
  session_id text NOT NULL,
  query text,
  category_code text REFERENCES categories(code),
  merchant_id bigint REFERENCES merchants(id) ON DELETE SET NULL,
  result_count integer,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE search_documents (
  id bigserial PRIMARY KEY,
  merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
  entity_type text NOT NULL CHECK (entity_type IN ('merchant', 'post')),
  entity_id bigint NOT NULL,
  content text NOT NULL,
  content_hash text NOT NULL,
  embedding vector(1024),
  embedding_model text,
  embedded_at timestamptz,
  search_vector tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', coalesce(content, ''))
  ) STORED,
  updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (entity_type, entity_id)
);

CREATE INDEX idx_categories_parent ON categories(parent_code);
CREATE INDEX idx_merchants_category ON merchants(category_code);
CREATE INDEX idx_posts_merchant ON merchant_posts(merchant_id);
CREATE INDEX idx_merchant_categories_category ON merchant_categories(category_code);
CREATE INDEX idx_merchant_terms_merchant ON merchant_search_terms(merchant_id);
CREATE INDEX idx_merchant_terms_normalized ON merchant_search_terms(normalized_term);
CREATE INDEX idx_events_created ON analytics_events(created_at);
CREATE INDEX idx_events_type_created ON analytics_events(event_type, created_at);
CREATE INDEX idx_events_query ON analytics_events(query);
CREATE INDEX idx_search_documents_merchant ON search_documents(merchant_id);
CREATE INDEX idx_search_documents_fts ON search_documents USING gin(search_vector);
CREATE INDEX idx_search_documents_trgm ON search_documents USING gin(content gin_trgm_ops);
