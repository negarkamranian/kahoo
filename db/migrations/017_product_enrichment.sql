-- Products follow Instagram collections, rather than replaceable merchant_posts IDs.
CREATE TABLE products (
    id bigserial PRIMARY KEY,
    merchant_id bigint NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
    collection_key text NOT NULL,
    caption text NOT NULL,
    permalink text NOT NULL,
    source_hash text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','processing','ready','not_product','failed')),
    result jsonb,
    model text,
    taxonomy_version text,
    pipeline_version text,
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    error text,
    claim_token uuid,
    started_at timestamptz,
    next_attempt_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at timestamptz,
    review_status text NOT NULL DEFAULT 'pending'
        CHECK (review_status IN ('pending','approved','rejected')),
    review_note text NOT NULL DEFAULT '',
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (merchant_id, collection_key)
);
CREATE INDEX products_queue ON products(status,next_attempt_at,id);
CREATE INDEX products_review ON products(review_status,id);

-- Keep evidence when an Instagram refresh replaces the merchant's recent posts.
CREATE TABLE product_images (
    product_id bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    position integer NOT NULL CHECK (position >= 1),
    source_url text NOT NULL,
    image_blob bytea NOT NULL,
    mime_type text NOT NULL,
    PRIMARY KEY (product_id,position)
);
CREATE TABLE product_enrichment_runs (
    id bigserial PRIMARY KEY,
    product_id bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    source_hash text NOT NULL,
    model text NOT NULL,
    taxonomy_version text NOT NULL,
    pipeline_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('ready','not_product','failed','superseded')),
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX product_runs_history ON product_enrichment_runs(product_id,id DESC);

CREATE FUNCTION reset_changed_product() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.source_hash IS DISTINCT FROM OLD.source_hash THEN
        NEW.status := 'pending';
        NEW.result := NULL;
        NEW.model := NULL;
        NEW.taxonomy_version := NULL;
        NEW.pipeline_version := NULL;
        NEW.attempts := 0;
        NEW.error := NULL;
        NEW.claim_token := NULL;
        NEW.started_at := NULL;
        NEW.processed_at := NULL;
        NEW.next_attempt_at := CURRENT_TIMESTAMP;
        NEW.review_status := 'pending';
        NEW.review_note := '';
        NEW.reviewed_at := NULL;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER product_evidence_changed BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION reset_changed_product();
