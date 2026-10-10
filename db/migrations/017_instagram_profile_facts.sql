-- Keep Instagram's own verification separate from directory verification.
ALTER TABLE merchants ADD COLUMN instagram_verified boolean;
ALTER TABLE merchants ADD COLUMN website_url text;
ALTER TABLE merchants ADD COLUMN profile_facts_source text;
ALTER TABLE merchants ADD COLUMN profile_facts_updated_at timestamptz;
