CREATE TABLE taxonomy_releases (
  id bigserial PRIMARY KEY,
  version text NOT NULL,
  locale text NOT NULL,
  source_url text NOT NULL,
  download_url text NOT NULL,
  source_commit text NOT NULL,
  source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  categories integer NOT NULL CHECK (categories > 0),
  attributes integer NOT NULL CHECK (attributes >= 0),
  value_count integer NOT NULL CHECK (value_count >= 0),
  source_archive bytea NOT NULL,
  license_text text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (version, locale, source_sha256)
);

CREATE TABLE taxonomy_categories (
  release_id bigint NOT NULL REFERENCES taxonomy_releases(id),
  id text NOT NULL,
  code text NOT NULL,
  level integer NOT NULL CHECK (level >= 0),
  name text NOT NULL,
  full_name text NOT NULL,
  parent_id text,
  position integer NOT NULL CHECK (position >= 0),
  attributes jsonb NOT NULL CHECK (jsonb_typeof(attributes) = 'array'),
  PRIMARY KEY (release_id, id),
  UNIQUE (release_id, code),
  UNIQUE (release_id, position),
  FOREIGN KEY (release_id, parent_id) REFERENCES taxonomy_categories(release_id, id)
    DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX taxonomy_categories_parent_idx ON taxonomy_categories(release_id, parent_id);

CREATE TABLE taxonomy_attributes (
  release_id bigint NOT NULL REFERENCES taxonomy_releases(id),
  id text NOT NULL,
  name text NOT NULL,
  handle text NOT NULL,
  description text NOT NULL,
  position integer NOT NULL CHECK (position >= 0),
  extended_attributes jsonb NOT NULL CHECK (jsonb_typeof(extended_attributes) = 'array'),
  allowed_values jsonb NOT NULL CHECK (jsonb_typeof(allowed_values) = 'array'),
  PRIMARY KEY (release_id, id),
  UNIQUE (release_id, handle),
  UNIQUE (release_id, position)
);

CREATE TABLE taxonomy_active_release (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  release_id bigint NOT NULL REFERENCES taxonomy_releases(id)
);

CREATE TABLE search_benchmarks (
  id bigserial PRIMARY KEY,
  name text NOT NULL UNIQUE CHECK (length(btrim(name)) > 0),
  source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  imported_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE search_benchmark_queries (
  id bigserial PRIMARY KEY,
  benchmark_id bigint NOT NULL REFERENCES search_benchmarks(id) ON DELETE CASCADE,
  query text NOT NULL CHECK (length(btrim(query)) > 0),
  position integer NOT NULL CHECK (position >= 0),
  UNIQUE (benchmark_id, query),
  UNIQUE (benchmark_id, position)
);

CREATE TABLE search_benchmark_relevance (
  query_id bigint NOT NULL REFERENCES search_benchmark_queries(id) ON DELETE CASCADE,
  handle text NOT NULL CHECK (handle ~ '^@[A-Za-z0-9_.]{1,30}$'),
  relevance smallint NOT NULL CHECK (relevance BETWEEN 1 AND 3),
  PRIMARY KEY (query_id, handle)
);

CREATE TABLE search_evaluations (
  id bigserial PRIMARY KEY,
  benchmark_name text NOT NULL,
  benchmark_sha256 text NOT NULL CHECK (benchmark_sha256 ~ '^[0-9a-f]{64}$'),
  benchmark_snapshot jsonb NOT NULL CHECK (jsonb_typeof(benchmark_snapshot) = 'object'),
  report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
