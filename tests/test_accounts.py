import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

from pydantic import ValidationError

from backend.models.auth import LoginRequest, LoginVerification, SessionContext
from backend.services import accounts

TOKEN = "a" * 43
SESSION_ID = "340d0b68-cbd9-4c55-9bf4-6bb355ef9bc9"
CHALLENGE_ID = "a29b21e0-dc56-4356-99ab-8a4bc493f924"
PHONE = "09123456789"


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.connection_patch = patch("backend.services.accounts.connect")
        connection = self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.database = connection.return_value.__enter__.return_value
        self.context = SessionContext(owner_id=12, session_id=SESSION_ID)

    def set_rows(self, *rows):
        self.database.execute.side_effect = [Mock(fetchone=Mock(return_value=row)) for row in rows]

    def session_row(self, logged_in=False):
        return {
            "user_id": 12,
            "public_session_id": UUID(SESSION_ID),
            "phone": PHONE if logged_in else None,
            "display_name": "حساب من" if logged_in else "",
            "phone_verified": False,
            "logged_in_at": datetime.now(timezone.utc) if logged_in else None,
        }

    def test_existing_session_is_looked_up_only_by_opaque_cookie_hash(self):
        self.set_rows(self.session_row(logged_in=True))
        session = accounts.open_session(TOKEN)
        self.assertIsNone(session.new_token)
        self.assertEqual(12, session.context.owner_id)
        self.assertEqual(SESSION_ID, session.context.session_id)
        self.assertEqual(PHONE, session.context.user.phone)
        self.assertFalse(session.context.user.phone_verified)
        statement, parameters = self.database.execute.call_args.args
        self.assertEqual((hashlib.sha256(TOKEN.encode()).hexdigest(),), parameters)
        self.assertIn("s.expires_at>CURRENT_TIMESTAMP", statement)
        self.assertNotIn("WHERE u.phone", statement)

    def test_guest_session_returns_no_login_user(self):
        self.set_rows(self.session_row())
        session = accounts.open_session(TOKEN)
        self.assertIsNone(session.context.user)
        self.assertIsNone(session.new_token)

    def test_unknown_or_expired_cookie_creates_a_new_owner_and_hashed_session(self):
        self.set_rows(None, {"id": 29}, None)
        session = accounts.open_session(TOKEN)
        self.assertEqual(29, session.context.owner_id)
        self.assertIsNone(session.context.user)
        self.assertNotEqual(TOKEN, session.new_token)
        self.assertEqual(43, len(session.new_token))
        self.assertEqual(4, UUID(session.context.session_id).version)
        insert = self.database.execute.call_args_list[-1].args
        self.assertIn("INSERT INTO user_sessions", insert[0])
        self.assertEqual(accounts.token_digest(session.new_token), insert[1][0])
        self.assertEqual((session.context.session_id, 29), insert[1][1:])
        self.assertNotIn(session.new_token, repr(self.database.execute.call_args_list))

    def test_malformed_cookie_is_not_used_as_an_identity(self):
        for token in (None, "", "session-id", "ا" * 43, "a" * 1000):
            with self.subTest(token=token):
                self.database.reset_mock()
                self.set_rows({"id": 3}, None)
                session = accounts.open_session(token)
                self.assertEqual(3, session.context.owner_id)
                self.assertEqual(2, self.database.execute.call_count)
                self.assertIn(
                    "INSERT INTO app_users", self.database.execute.call_args_list[0].args[0]
                )

    def test_request_persists_phone_and_challenge_bound_to_owner_and_session(self):
        self.set_rows({"id": 12}, {"count": 0}, None)
        challenge = accounts.request_login(self.context, LoginRequest(phone=PHONE))
        self.assertEqual(PHONE, challenge.phone)
        self.assertEqual(4, UUID(challenge.challenge_id).version)
        calls = self.database.execute.call_args_list
        self.assertIn("FOR UPDATE", calls[0].args[0])
        self.assertEqual((12, SESSION_ID), calls[0].args[1])
        self.assertIn("FOR KEY SHARE OF s", calls[0].args[0])
        self.assertEqual((challenge.challenge_id, 12, SESSION_ID, PHONE), calls[-1].args[1])

    def test_rate_limit_is_checked_under_owner_lock_and_does_not_issue_challenge(self):
        self.set_rows({"id": 12}, {"count": 5})
        with self.assertRaises(accounts.LoginFlowError) as caught:
            accounts.request_login(self.context, LoginRequest(phone=PHONE))
        self.assertEqual("login_rate_limited", caught.exception.code)
        self.assertEqual(429, caught.exception.status_code)
        self.assertEqual(2, self.database.execute.call_count)

    def test_missing_owner_does_not_issue_challenge(self):
        self.set_rows(None)
        with self.assertRaises(accounts.LoginFlowError) as caught:
            accounts.request_login(self.context, LoginRequest(phone=PHONE))
        self.assertEqual("invalid_session", caught.exception.code)
        self.assertEqual(1, self.database.execute.call_count)

    def test_demo_verification_promotes_current_owner_without_verifying_or_merging_phone(self):
        for code in ("00000", "12345", "99999"):
            with self.subTest(code=code):
                self.database.reset_mock()
                self.set_rows(
                    {"user_id": 12},
                    {"id": 12, "phone": PHONE, "display_name": "حساب من", "phone_verified": False},
                )
                result = accounts.verify_login(
                    self.context,
                    LoginVerification(phone=PHONE, challenge_id=CHALLENGE_ID, code=code),
                )
                self.assertEqual(12, result.user.id)
                self.assertFalse(result.user.phone_verified)
                consume, update = [call.args for call in self.database.execute.call_args_list]
                self.assertEqual((CHALLENGE_ID, 12, SESSION_ID, PHONE), consume[1])
                self.assertIn("consumed_at IS NULL", consume[0])
                self.assertIn("expires_at>CURRENT_TIMESTAMP", consume[0])
                self.assertIn("RETURNING user_id", consume[0])
                self.assertIn("phone_verified=false", update[0])
                self.assertIn("WHERE id=%s", update[0])
                self.assertEqual((PHONE, "حساب من", 12), update[1])
                self.assertNotIn("SELECT", update[0])

    def test_rejected_challenge_never_mutates_a_user(self):
        self.set_rows(None)
        with self.assertRaises(accounts.LoginFlowError) as caught:
            accounts.verify_login(
                self.context,
                LoginVerification(phone=PHONE, challenge_id=CHALLENGE_ID, code="12345"),
            )
        self.assertEqual("invalid_challenge", caught.exception.code)
        self.assertEqual(1, self.database.execute.call_count)

    def test_challenge_verification_uses_the_cookie_owner_even_for_the_same_phone(self):
        self.set_rows(None)
        stranger = SessionContext(owner_id=81, session_id="bf87cc0b-725f-4de9-ab5e-0d9d52f6f559")
        with self.assertRaises(accounts.LoginFlowError):
            accounts.verify_login(
                stranger,
                LoginVerification(phone=PHONE, challenge_id=CHALLENGE_ID, code="12345"),
            )
        self.assertEqual(
            (CHALLENGE_ID, 81, stranger.session_id, PHONE), self.database.execute.call_args.args[1]
        )

    def test_logout_revokes_only_session_and_preserves_owner_and_saved_data(self):
        accounts.revoke_session(TOKEN)
        statement, parameters = self.database.execute.call_args.args
        self.assertEqual("DELETE FROM user_sessions WHERE token_hash=%s", statement)
        self.assertEqual((accounts.token_digest(TOKEN),), parameters)
        self.database.reset_mock()
        accounts.revoke_session("invalid")
        self.database.execute.assert_not_called()

    def test_login_inputs_require_iranian_phone_uuid_and_five_digits(self):
        for phone in ("", "12345678901", "0912345678", "۰۹۱۲۳۴۵۶۷۸۹", 9123456789):
            with self.subTest(phone=phone), self.assertRaises(ValidationError):
                LoginRequest(phone=phone)
        for code in ("abcde", "۱۲۳۴۵", "1234", "123456", 12345):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                LoginVerification(phone=PHONE, challenge_id=CHALLENGE_ID, code=code)
        with self.assertRaises(ValidationError):
            LoginVerification(phone=PHONE, challenge_id="not-a-challenge", code="12345")

    def test_schema_has_no_phone_identity_constraint_and_preserves_challenge_lifecycle(self):
        migration = Path("db/migrations/014_accounts.sql").read_text(encoding="utf-8")
        self.assertIn("id bigserial PRIMARY KEY", migration)
        self.assertIn("token_hash text PRIMARY KEY", migration)
        self.assertIn(
            "session_id uuid NOT NULL REFERENCES user_sessions(public_session_id)", migration
        )
        self.assertIn("consumed_at timestamptz", migration)
        self.assertNotIn("phone text UNIQUE", migration)
        self.assertNotIn("UNIQUE(phone)", migration)


if __name__ == "__main__":
    unittest.main()
