import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from backend.models.auth import LoginChallenge, LoginResult, LoginUser, SessionContext
from backend.server.account_routes import COOKIE_NAME, router
from backend.server.routes import http_error_response, validation_error_response
from backend.services.accounts import LoginFlowError, OpenedSession

TOKEN = "a" * 43
SESSION_ID = "340d0b68-cbd9-4c55-9bf4-6bb355ef9bc9"
CHALLENGE_ID = "a29b21e0-dc56-4356-99ab-8a4bc493f924"
PHONE = "09123456789"
MUTATION_HEADERS = {"X-Kahoo-Saved": "1"}


class AccountHttpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        app = FastAPI(
            exception_handlers={
                RequestValidationError: validation_error_response,
                HTTPException: http_error_response,
            }
        )
        app.include_router(router)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        )
        self.addAsyncCleanup(self.client.aclose)
        session_patch = patch("backend.server.account_routes.open_session")
        self.session_service = session_patch.start()
        self.addCleanup(session_patch.stop)
        self.context = SessionContext(owner_id=12, session_id=SESSION_ID)
        self.session_service.return_value = OpenedSession(self.context, TOKEN)

    async def test_guest_bootstrap_sets_an_opaque_httponly_cookie_without_exposing_owner(self):
        response = await self.client.get("/api/session")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"session_id": SESSION_ID, "user": None}, response.json())
        cookie = response.headers["set-cookie"]
        self.assertIn(f"{COOKIE_NAME}={TOKEN}", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertIn("Max-Age=31536000", cookie)
        self.assertIn("Path=/", cookie)
        self.assertNotIn("Secure", cookie)
        self.assertEqual("private, no-store", response.headers["cache-control"])
        self.assertNotIn(TOKEN, response.text)

    async def test_cookie_is_secure_for_https_and_existing_session_is_not_replaced(self):
        response = await self.client.get("https://testserver/api/session")
        self.assertIn("Secure", response.headers["set-cookie"])
        self.client.cookies.set(COOKIE_NAME, TOKEN)
        self.session_service.return_value = OpenedSession(self.context)
        response = await self.client.get("/api/session")
        self.session_service.assert_called_with(TOKEN)
        self.assertNotIn("set-cookie", response.headers)

    async def test_logged_in_session_returns_persistent_user_without_claiming_phone_verification(
        self,
    ):
        user = LoginUser(id=12, phone=PHONE, display_name="حساب من", phone_verified=False)
        self.session_service.return_value = OpenedSession(
            SessionContext(owner_id=12, session_id=SESSION_ID, user=user)
        )
        response = await self.client.get("/api/session")
        self.assertEqual(user.model_dump(), response.json()["user"])
        self.assertFalse(response.json()["user"]["phone_verified"])

    @patch("backend.server.account_routes.request_login")
    async def test_login_request_receives_cookie_owned_context_and_preserves_response_shape(
        self, request
    ):
        request.return_value = LoginChallenge(challenge_id=CHALLENGE_ID, phone=PHONE)
        response = await self.client.post(
            "/api/login/request", json={"phone": PHONE}, headers=MUTATION_HEADERS
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual({"challenge_id": CHALLENGE_ID, "phone": PHONE}, response.json())
        context, payload = request.call_args.args
        self.assertEqual(self.context, context)
        self.assertEqual(PHONE, payload.phone)

    @patch("backend.server.account_routes.verify_login")
    async def test_login_verification_requires_challenge_and_returns_unverified_current_owner(
        self, verify
    ):
        verify.return_value = LoginResult(
            user=LoginUser(id=12, phone=PHONE, display_name="حساب من")
        )
        response = await self.client.post(
            "/api/login/verify",
            json={"phone": PHONE, "challenge_id": CHALLENGE_ID, "code": "12345"},
            headers=MUTATION_HEADERS,
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(12, response.json()["user"]["id"])
        self.assertFalse(response.json()["user"]["phone_verified"])
        context, login = verify.call_args.args
        self.assertEqual(self.context, context)
        self.assertEqual(CHALLENGE_ID, login.challenge_id)

    async def test_simple_and_cross_origin_account_mutations_are_rejected_before_session_access(
        self,
    ):
        for path in ("/api/login/request", "/api/login/verify", "/api/logout"):
            for headers in (
                {},
                {**MUTATION_HEADERS, "Sec-Fetch-Site": "cross-site"},
                {**MUTATION_HEADERS, "Origin": "https://other.example"},
                {**MUTATION_HEADERS, "Origin": "https://testserver"},
                {**MUTATION_HEADERS, "Origin": "http://["},
            ):
                with self.subTest(path=path, headers=headers):
                    response = await self.client.post(path, json={}, headers=headers)
                    self.assertEqual(403, response.status_code)
                    self.assertEqual({"error": "account_request_forbidden"}, response.json())
        self.session_service.assert_not_called()

    @patch("backend.server.account_routes.request_login")
    async def test_same_origin_request_is_allowed(self, request):
        request.return_value = LoginChallenge(challenge_id=CHALLENGE_ID, phone=PHONE)
        response = await self.client.post(
            "/api/login/request",
            json={"phone": PHONE},
            headers={
                **MUTATION_HEADERS,
                "Origin": "http://testserver",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        self.assertEqual(200, response.status_code)

    @patch("backend.server.account_routes.verify_login")
    @patch("backend.server.account_routes.request_login")
    async def test_invalid_input_never_opens_session_or_reaches_account_services(
        self, request, verify
    ):
        for payload in ({"phone": "123"}, {"phone": PHONE, "challenge_id": "bad", "code": "abcde"}):
            path = "/api/login/verify" if "code" in payload else "/api/login/request"
            response = await self.client.post(path, json=payload, headers=MUTATION_HEADERS)
            self.assertEqual(400, response.status_code)
        self.session_service.assert_not_called()
        request.assert_not_called()
        verify.assert_not_called()

    @patch(
        "backend.server.account_routes.verify_login",
        side_effect=LoginFlowError("invalid_challenge"),
    )
    async def test_expired_consumed_or_wrong_owner_challenges_return_clear_client_error(
        self, _verify
    ):
        response = await self.client.post(
            "/api/login/verify",
            json={"phone": PHONE, "challenge_id": CHALLENGE_ID, "code": "12345"},
            headers=MUTATION_HEADERS,
        )
        self.assertEqual(400, response.status_code)
        self.assertEqual({"error": "invalid_challenge"}, response.json())

    @patch(
        "backend.server.account_routes.request_login",
        side_effect=LoginFlowError("login_rate_limited", 429),
    )
    async def test_request_rate_limit_is_reported_as_429(self, _request):
        response = await self.client.post(
            "/api/login/request", json={"phone": PHONE}, headers=MUTATION_HEADERS
        )
        self.assertEqual(429, response.status_code)
        self.assertEqual({"error": "login_rate_limited"}, response.json())

    @patch("backend.server.account_routes.revoke_session")
    async def test_logout_revokes_cookie_and_does_not_create_another_owner(self, revoke):
        self.client.cookies.set(COOKIE_NAME, TOKEN)
        response = await self.client.post("/api/logout", headers=MUTATION_HEADERS)
        self.assertEqual(200, response.status_code)
        self.assertEqual({"logged_out": True}, response.json())
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        self.assertEqual("private, no-store", response.headers["cache-control"])
        revoke.assert_called_once_with(TOKEN)
        self.session_service.assert_not_called()

    async def test_oversized_body_is_rejected_by_existing_request_guard(self):
        response = await self.client.post(
            "/api/login/request",
            content=b"x",
            headers={"Content-Length": "1048577", **MUTATION_HEADERS},
        )
        self.assertEqual(413, response.status_code)
        self.assertEqual({"error": "request_too_large"}, response.json())
        self.session_service.assert_not_called()


if __name__ == "__main__":
    unittest.main()
