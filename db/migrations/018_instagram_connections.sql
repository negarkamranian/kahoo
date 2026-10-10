-- One-time authorization states are bound to the initiating browser session.
CREATE TABLE instagram_oauth_states (
  state_hash text PRIMARY KEY CHECK (state_hash ~ '^[0-9a-f]{64}$'),
  session_id uuid NOT NULL REFERENCES user_sessions(public_session_id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '10 minutes',
  consumed_at timestamptz
);
CREATE INDEX instagram_oauth_states_session_idx ON instagram_oauth_states(session_id, created_at);

-- Tokens are encrypted using the server's separately configured Fernet key.
CREATE TABLE instagram_connections (
  instagram_user_id text PRIMARY KEY,
  merchant_id bigint NOT NULL UNIQUE REFERENCES merchants(id) ON DELETE CASCADE,
  owner_id bigint NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  username text NOT NULL,
  token_ciphertext text NOT NULL,
  expires_at timestamptz NOT NULL,
  connected_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  refreshed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX instagram_connections_owner_idx ON instagram_connections(owner_id);
