CREATE TABLE merchant_exclusions (
  handle text PRIMARY KEY,
  reason text NOT NULL DEFAULT 'admin_removed',
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
