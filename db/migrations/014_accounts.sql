-- Guest ownership and demo login are persistent. Phone numbers are unverified
-- profile data: they deliberately have no uniqueness or identity lookup index.
CREATE TABLE app_users (
  id bigserial PRIMARY KEY,
  phone text CHECK (phone IS NULL OR phone ~ '^09[0-9]{9}$'),
  display_name text NOT NULL DEFAULT '',
  phone_verified boolean NOT NULL DEFAULT false,
  logged_in_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_sessions (
  token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  public_session_id uuid NOT NULL UNIQUE,
  user_id bigint NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '1 year'
);
CREATE INDEX user_sessions_user_id_idx ON user_sessions(user_id);
CREATE INDEX user_sessions_expires_at_idx ON user_sessions(expires_at);

CREATE TABLE login_challenges (
  challenge_id uuid PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  session_id uuid NOT NULL REFERENCES user_sessions(public_session_id) ON DELETE CASCADE,
  phone text NOT NULL CHECK (phone ~ '^09[0-9]{9}$'),
  created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP + INTERVAL '5 minutes',
  consumed_at timestamptz
);
CREATE INDEX login_challenges_user_created_idx ON login_challenges(user_id, created_at);
