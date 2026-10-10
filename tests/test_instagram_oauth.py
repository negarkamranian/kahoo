"""Provider contracts, callback security and private token persistence."""

import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import DEFAULT, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient

from backend.instagram.oauth import (
    InstagramConnectionError,
    authorization_url,
    authorized_profile,
    exchange_code,
    login_configured,
    provider_request,
)
from backend.models.auth import SessionContext
from backend.models.instagram.oauth import AuthorizedProfile, InstagramToken
from backend.server.app import app
from backend.services.instagram_connections import (
    begin_authorization,
    complete_authorization,
    connection_status,
    consume_authorization,
    find_authorized_merchant,
    store_connection,
)
from backend.services.instagram_credentials import current_access_token

CONTEXT = SessionContext(owner_id=7, session_id="00000000-0000-4000-8000-000000000007")
PROFILE = {"user_id": "1234", "username": "real_shop", "account_type": "BUSINESS", "name": "Shop"}


def configured():
    return patch.multiple(
        "backend.instagram.oauth.settings",
        instagram_app_id="123",
        instagram_app_secret="private-app-secret",
        instagram_redirect_uri="https://kahoo.ir/api/instagram/callback",
        instagram_token_encryption_key=Fernet.generate_key().decode(),
    )


class InstagramProviderTests(unittest.TestCase):
    def setUp(self):
        config = configured()
        config.start()
        self.addCleanup(config.stop)

    def test_authorization_requests_only_basic_permission_and_fixed_callback(self):
        self.assertTrue(login_configured())
        url = urlsplit(authorization_url("random-state"))
        self.assertEqual("www.instagram.com", url.hostname)
        params = parse_qs(url.query)
        self.assertEqual(["instagram_business_basic"], params["scope"])
        self.assertEqual(["https://kahoo.ir/api/instagram/callback"], params["redirect_uri"])
        self.assertEqual(["random-state"], params["state"])
        self.assertNotIn("private-app-secret", url.query)
        for value in ("", "http://kahoo.ir/api/instagram/callback", "https://kahoo.ir/wrong"):
            with patch("backend.instagram.oauth.settings.instagram_redirect_uri", value):
                self.assertFalse(login_configured())

    @patch("backend.instagram.oauth.urlopen")
    def test_code_exchange_keeps_secret_in_post_and_extends_token(self, urlopen):
        grant = {"access_token": "short-secret", "permissions": ["instagram_business_basic"]}
        for payload in (grant, {"data": [grant]}):
            urlopen.reset_mock()
            urlopen.side_effect = [
                io.BytesIO(json.dumps(payload).encode()),
                io.BytesIO(
                    json.dumps({"access_token": "long-secret", "expires_in": 5184000}).encode()
                ),
            ]
            token = exchange_code("one-time-code")
            self.assertEqual("long-secret", token.access_token)
            self.assertNotIn("long-secret", repr(token))
            request = urlopen.call_args_list[0].args[0]
            self.assertEqual("POST", request.get_method())
            self.assertNotIn("private-app-secret", request.full_url)
            form = parse_qs(request.data.decode())
            self.assertEqual(["one-time-code"], form["code"])
            self.assertEqual(["private-app-secret"], form["client_secret"])
            extended = parse_qs(urlsplit(urlopen.call_args_list[1].args[0].full_url).query)
            self.assertEqual(["ig_exchange_token"], extended["grant_type"])

    @patch("backend.instagram.oauth.provider_request")
    def test_missing_permission_stops_before_long_lived_exchange(self, request):
        request.return_value = {"data": [{"access_token": "secret", "permissions": []}]}
        with self.assertRaisesRegex(InstagramConnectionError, "instagram_permission_denied"):
            exchange_code("code")
        self.assertEqual(1, request.call_count)

    @patch("backend.instagram.oauth.provider_request")
    def test_authorized_profile_retains_carousel_images_and_video_thumbnail(self, request):
        request.side_effect = [
            {**PROFILE, "name": "", "followers_count": 123},
            {
                "data": [
                    {
                        "id": "album",
                        "media_type": "CAROUSEL_ALBUM",
                        "permalink": "https://www.instagram.com/p/album/",
                        "children": {
                            "data": [
                                {
                                    "id": "photo",
                                    "media_type": "IMAGE",
                                    "media_url": "https://cdn.test/photo.jpg",
                                },
                                {
                                    "id": "video",
                                    "media_type": "VIDEO",
                                    "thumbnail_url": "https://cdn.test/video.jpg",
                                },
                            ]
                        },
                    }
                ]
            },
        ]
        identity = authorized_profile("private-token")
        profile = identity.to_profile()
        self.assertEqual("@real_shop", identity.handle)
        self.assertEqual("real_shop", profile.name)
        self.assertEqual("instagram_oauth", profile.source)
        self.assertEqual(2, len(profile.posts[0].media))
        self.assertEqual("https://cdn.test/video.jpg", profile.posts[0].media[1].image_url)
        self.assertEqual("private-token", request.call_args_list[0].kwargs["token"])

    @patch("backend.instagram.oauth.urlopen")
    def test_graph_token_is_in_header_and_provider_errors_are_redacted(self, urlopen):
        urlopen.return_value = io.BytesIO(b'{"error":{"message":"secret-token"}}')
        with self.assertRaisesRegex(InstagramConnectionError, "^instagram_provider_failed$"):
            provider_request("https://graph.instagram.com/me", token="secret-token")
        request = urlopen.call_args.args[0]
        self.assertNotIn("secret-token", request.full_url)
        self.assertEqual("Bearer secret-token", request.headers["Authorization"])


class InstagramPersistenceTests(unittest.TestCase):
    def setUp(self):
        config = configured()
        config.start()
        self.addCleanup(config.stop)

    @patch("backend.services.instagram_connections.connect")
    def test_state_is_hashed_and_bound_to_initiating_session(self, connect):
        db = connect.return_value.__enter__.return_value
        db.execute.return_value.fetchone.return_value = {"count": 0}
        url = begin_authorization(CONTEXT)
        state = parse_qs(urlsplit(url).query)["state"][0]
        self.assertEqual(43, len(state))
        params = db.execute.call_args.args[1]
        self.assertEqual(CONTEXT.session_id, params[1])
        self.assertEqual(64, len(params[0]))
        self.assertNotEqual(state, params[0])

    @patch("backend.services.instagram_connections.connect")
    def test_replayed_expired_and_foreign_states_cannot_be_consumed(self, connect):
        db = connect.return_value.__enter__.return_value
        db.execute.return_value.fetchone.return_value = None
        with self.assertRaisesRegex(InstagramConnectionError, "instagram_invalid_state"):
            consume_authorization(CONTEXT, "a" * 43)
        sql, params = db.execute.call_args.args
        self.assertIn("consumed_at IS NULL", sql)
        self.assertIn("expires_at>CURRENT_TIMESTAMP", sql)
        self.assertEqual(CONTEXT.session_id, params[1])
        db.reset_mock()
        with self.assertRaises(InstagramConnectionError):
            consume_authorization(CONTEXT, "malformed")
        db.execute.assert_not_called()

    def test_saved_token_is_encrypted_and_owned_by_current_session(self):
        db = MagicMock()
        token = InstagramToken(access_token="private-token", expires_in=5184000)
        store_connection(db, CONTEXT, AuthorizedProfile.model_validate(PROFILE), token, 19)
        params = db.execute.call_args.args[1]
        self.assertEqual(("1234", 19, CONTEXT.owner_id, "real_shop"), params[:4])
        self.assertNotIn("private-token", params[4])
        from backend.instagram.oauth import token_cipher  # local to use configured key

        cipher = token_cipher()
        self.assertEqual(b"private-token", cipher.decrypt(params[4].encode()))
        with self.assertRaises(InvalidToken):
            cipher.decrypt((params[4][:-2] + "xx").encode())

    @patch("backend.services.instagram_connections.connect")
    def test_connection_status_is_owner_scoped_and_never_contains_tokens(self, connect):
        db = connect.return_value.__enter__.return_value
        db.execute.return_value = [
            {
                "merchant_id": 19,
                "name": "Shop",
                "handle": "@real_shop",
                "expires_at": datetime.now(timezone.utc) + timedelta(days=60),
                "needs_reconnect": False,
                "token_ciphertext": "private-token",
            }
        ]
        status = connection_status(CONTEXT)
        self.assertEqual((CONTEXT.owner_id,), db.execute.call_args.args[1])
        self.assertEqual(19, status.connections[0].merchant_id)
        self.assertNotIn("private-token", status.model_dump_json())
        self.assertNotIn("token_ciphertext", status.model_dump_json())

    def test_successful_import_persists_real_identity_and_records_completion(self):
        with patch.multiple(
            "backend.services.instagram_connections",
            connect=DEFAULT,
            exchange_code=DEFAULT,
            authorized_profile=DEFAULT,
            find_authorized_merchant=DEFAULT,
            save_profile_details=DEFAULT,
            save_imported_avatar=DEFAULT,
            replace_profile_posts=DEFAULT,
            sync_search_index=DEFAULT,
        ) as mocks:
            mocks["exchange_code"].return_value = InstagramToken(
                access_token="secret", expires_in=5184000
            )
            mocks["authorized_profile"].return_value = AuthorizedProfile.model_validate(PROFILE)
            mocks["find_authorized_merchant"].return_value = 19
            self.assertEqual(19, complete_authorization(CONTEXT, "real-code"))
            db = mocks["connect"].return_value.__enter__.return_value
            inserts = [
                call
                for call in db.execute.call_args_list
                if "INSERT INTO instagram_connections" in call.args[0]
            ]
            self.assertEqual(1, len(inserts))
            self.assertEqual(("1234", 19, 7, "real_shop"), inserts[0].args[1][:4])
            self.assertNotEqual("secret", inserts[0].args[1][4])
            mocks["replace_profile_posts"].assert_called_once()
            mocks["sync_search_index"].assert_called_once_with(db)
            self.assertTrue(
                any("'oauth_completed'" in call.args[0] for call in db.execute.call_args_list)
            )

    @patch("backend.services.instagram_credentials.refresh_token")
    def test_expired_tokens_require_reauthorization_and_near_expiry_tokens_refresh(self, refresh):
        from backend.instagram.oauth import token_cipher

        cipher = token_cipher()
        now = datetime.now(timezone.utc)
        row = {
            "instagram_user_id": "1234",
            "token_ciphertext": cipher.encrypt(b"old-token").decode(),
            "expires_at": now - timedelta(seconds=1),
            "refreshed_at": now - timedelta(days=10),
        }
        db = MagicMock()
        with self.assertRaisesRegex(InstagramConnectionError, "instagram_token_expired"):
            current_access_token(db, row)
        refresh.assert_not_called()
        row["expires_at"] = now + timedelta(days=2)
        refresh.return_value = InstagramToken(access_token="renewed-token", expires_in=5184000)
        self.assertEqual("renewed-token", current_access_token(db, row))
        refresh.assert_called_once_with("old-token")
        self.assertEqual(b"renewed-token", cipher.decrypt(db.execute.call_args.args[1][0].encode()))

    def test_excluded_shops_cannot_be_reimported_by_oauth(self):
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = {"handle": "@real_shop"}
        with self.assertRaisesRegex(InstagramConnectionError, "instagram_shop_excluded"):
            find_authorized_merchant(db, AuthorizedProfile.model_validate(PROFILE))
        self.assertFalse(
            any("INSERT INTO merchants" in call.args[0] for call in db.execute.call_args_list)
        )

    @patch("backend.services.instagram_connections.sync_search_index")
    @patch("backend.services.instagram_connections.store_connection")
    @patch("backend.services.instagram_connections.replace_profile_posts")
    @patch("backend.services.instagram_connections.save_imported_avatar")
    @patch("backend.services.instagram_connections.save_profile_details")
    @patch("backend.services.instagram_connections.find_authorized_merchant", return_value=19)
    @patch("backend.services.instagram_connections.connect")
    @patch("backend.services.instagram_connections.authorized_profile")
    @patch("backend.services.instagram_connections.exchange_code")
    def test_image_failure_rolls_back_import_and_never_stores_connection(
        self, exchange, profile, connect, find, save, avatar, posts, store, index
    ):
        exchange.return_value = InstagramToken(access_token="secret", expires_in=5184000)
        profile.return_value = AuthorizedProfile.model_validate(PROFILE)
        posts.side_effect = OSError("image download failed")
        with self.assertRaises(OSError):
            complete_authorization(CONTEXT, "code")
        find.assert_called_once()
        save.assert_called_once()
        avatar.assert_called_once()
        store.assert_not_called()
        index.assert_not_called()
        self.assertIs(OSError, connect.return_value.__exit__.call_args.args[0])


class InstagramOAuthHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, headers={"X-Kahoo-Saved": "1"})
        self.addCleanup(self.client.close)
        config = configured()
        config.start()
        self.addCleanup(config.stop)
        session = patch("backend.server.instagram_routes.ensure_session", return_value=CONTEXT)
        session.start()
        self.addCleanup(session.stop)
        callback = patch("backend.server.instagram_routes.callback_session", return_value=CONTEXT)
        callback.start()
        self.addCleanup(callback.stop)

    @patch(
        "backend.server.instagram_routes.begin_authorization",
        return_value="https://www.instagram.com/oauth/authorize?state=abc",
    )
    def test_start_is_same_origin_post_and_never_returns_tokens(self, begin):
        response = self.client.post("/api/instagram/connect")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"authorization_url": begin.return_value}, response.json())
        for headers in (
            {"Origin": "https://evil.test"},
            {"Sec-Fetch-Site": "cross-site"},
            {"X-Kahoo-Saved": "0"},
        ):
            self.assertEqual(
                403, self.client.post("/api/instagram/connect", headers=headers).status_code
            )
        self.assertEqual(1, begin.call_count)

    @patch("backend.server.instagram_routes.login_configured", return_value=False)
    @patch("backend.server.instagram_routes.begin_authorization")
    def test_missing_credentials_do_not_start_a_demo(self, begin, _configured):
        response = self.client.post("/api/instagram/connect")
        self.assertEqual(503, response.status_code)
        self.assertEqual({"error": "instagram_not_configured"}, response.json())
        begin.assert_not_called()

    @patch("backend.server.instagram_routes.complete_authorization", return_value=19)
    @patch("backend.server.instagram_routes.consume_authorization")
    def test_callback_only_reports_success_after_verified_import(self, consume, complete):
        response = self.client.get(
            "/api/instagram/callback?state=state&code=real-code", follow_redirects=False
        )
        self.assertEqual(303, response.status_code)
        self.assertEqual("/?instagram=connected#connect", response.headers["Location"])
        self.assertEqual("private, no-store", response.headers["Cache-Control"])
        self.assertEqual("no-referrer", response.headers["Referrer-Policy"])
        consume.assert_called_once_with(CONTEXT, "state")
        complete.assert_called_once_with(CONTEXT, "real-code")

    @patch("backend.server.instagram_routes.complete_authorization")
    @patch("backend.server.instagram_routes.consume_authorization")
    def test_denial_and_invalid_state_never_exchange_the_code(self, consume, complete):
        response = self.client.get(
            "/api/instagram/callback?state=state&error=access_denied", follow_redirects=False
        )
        self.assertIn("instagram_permission_denied", response.headers["Location"])
        consume.side_effect = InstagramConnectionError("instagram_invalid_state")
        response = self.client.get(
            "/api/instagram/callback?state=other&code=code", follow_redirects=False
        )
        self.assertIn("instagram_invalid_state", response.headers["Location"])
        complete.assert_not_called()

    @patch("backend.server.instagram_routes.consume_authorization")
    @patch(
        "backend.server.instagram_routes.complete_authorization",
        side_effect=OSError("secret-token-in-provider-url"),
    )
    def test_provider_failure_cannot_leak_credentials_or_claim_success(self, _complete, _consume):
        response = self.client.get(
            "/api/instagram/callback?state=state&code=code", follow_redirects=False
        )
        self.assertIn("instagram_connection_failed", response.headers["Location"])
        self.assertNotIn("secret-token", str(response.headers) + response.text)
