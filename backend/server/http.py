import hmac
import json
import mimetypes
import uuid
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from pydantic import JsonValue, TypeAdapter, ValidationError

from backend.config import PROJECT_ROOT, settings
from backend.database import connect
from backend.models.analytics import AnalyticsEvent, MetricsPeriod
from backend.models.auth import LoginRequest, LoginVerification
from backend.models.merchants import AdminMerchantQuery, MerchantImport
from backend.search.service import merchants
from backend.search.suggestions import search_suggestions
from backend.serialization import json_default
from backend.services.analytics import admin_metrics, record_event
from backend.services.categories import category_tree
from backend.services.merchants import (
    add_or_refresh_merchant,
    admin_merchants,
    merchant_detail,
    remove_merchant,
)

PUBLIC_ROOT = PROJECT_ROOT / "public"
JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


MAX_REQUEST_BYTES = 1_048_576


class RequestError(ValueError):
    """A malformed request body with its HTTP response status."""

    def __init__(self, code, status=400):
        super().__init__(code)
        self.code = code
        self.status = status


def admin_mutation_authorized(headers):
    configured = settings.admin_token
    if not configured:
        return True
    supplied = headers.get("X-Kahoo-Admin-Token", "")
    return bool(supplied) and hmac.compare_digest(configured, supplied)


def import_demo_merchant():
    # A real OAuth callback would upsert the authenticated account. The demo must
    # never create a made-up public identity in the directory.
    return {"created": False, "mode": "oauth_demo"}


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, data, content_type, status=200, cache_control=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, default=json_default).encode()
        self.send_bytes(body, "application/json; charset=utf-8", status)

    GET_ROUTES = {
        "/api/categories": "_get_categories",
        "/api/search/suggestions": "_get_suggestions",
        "/api/merchants": "_get_merchants",
        "/api/admin/metrics": "_get_admin_metrics",
        "/api/admin/merchants": "_get_admin_merchants",
    }
    GET_PREFIXES = {
        "/api/merchants/": "_get_merchant_detail",
        "/api/media/": "_get_media",
        "/api/avatars/": "_get_avatar",
    }

    def do_GET(self):
        parsed = urlparse(self.path)
        handler = self.GET_ROUTES.get(parsed.path)
        if handler:
            return getattr(self, handler)(parsed.query)
        for prefix, handler in self.GET_PREFIXES.items():
            if parsed.path.startswith(prefix):
                return getattr(self, handler)(parsed.path)
        return self._get_static_file(parsed.path)

    def _get_categories(self, _query):
        return self.send_json(category_tree())

    def _get_suggestions(self, query):
        args = parse_qs(query)
        return self.send_json(search_suggestions(args.get("q", [""])[0]))

    def _get_merchants(self, query):
        args = parse_qs(query)
        category = args.get("category", [None])[0]
        query = args.get("q", [""])[0]
        result = merchants(category, query)
        session_id = self.headers.get("X-Kahoo-Session")
        if session_id is not None and (query or category):
            event_type = "category_view"
            if query:
                event_type = "search"
            event = AnalyticsEvent(
                event_type=event_type,
                session_id=session_id,
                query=query,
                category_code=category,
                result_count=len(result),
            )
            record_event(event)
        return self.send_json(result)

    def _get_merchant_detail(self, path):
        try:
            merchant_id = int(path.rsplit("/", 1)[1])
        except ValueError:
            return self.send_error(404)
        result = merchant_detail(merchant_id)
        if result is None:
            return self.send_error(404)
        return self.send_json(result)

    def _get_admin_metrics(self, query):
        args = parse_qs(query, keep_blank_values=True)
        try:
            period = MetricsPeriod(int(args.get("days", [MetricsPeriod.MONTH.value])[0]))
        except ValueError:
            return self.send_json({"error": "invalid_metrics_period"}, 400)
        return self.send_json(admin_metrics(period))

    def _get_admin_merchants(self, query):
        args = parse_qs(query, keep_blank_values=True)
        try:
            pagination = {key: int(args[key][0]) for key in ("limit", "offset") if key in args}
            request = AdminMerchantQuery(query=args.get("q", [""])[0], **pagination)
        except ValueError:
            return self.send_json({"error": "invalid_pagination"}, 400)
        return self.send_json(admin_merchants(request))

    def _get_media(self, path):
        try:
            post_id = int(path.rsplit("/", 1)[1])
        except ValueError:
            return self.send_error(404)
        with connect() as db:
            media = db.execute(
                "SELECT image_blob,mime_type FROM merchant_posts WHERE id=%s", (post_id,)
            ).fetchone()
        if not media or media["image_blob"] is None:
            return self.send_error(404)
        return self.send_bytes(
            media["image_blob"],
            media["mime_type"] or "application/octet-stream",
            cache_control="public, max-age=86400",
        )

    def _get_avatar(self, path):
        try:
            merchant_id = int(path.rsplit("/", 1)[1])
        except ValueError:
            return self.send_error(404)
        with connect() as db:
            avatar = db.execute(
                "SELECT avatar_blob,avatar_mime_type FROM merchants WHERE id=%s", (merchant_id,)
            ).fetchone()
        if not avatar or avatar["avatar_blob"] is None:
            return self.send_error(404)
        return self.send_bytes(
            avatar["avatar_blob"],
            avatar["avatar_mime_type"] or "application/octet-stream",
            cache_control="public, max-age=86400",
        )

    def _get_static_file(self, request_path):
        if request_path == "/":
            request_path = "/index.html"
        path = PUBLIC_ROOT / request_path.lstrip("/")
        if not path.is_file() or PUBLIC_ROOT not in path.resolve().parents:
            return self.send_error(404)
        return self.send_bytes(
            path.read_bytes(), mimetypes.guess_type(path)[0] or "application/octet-stream"
        )

    POST_ROUTES = {
        "/api/analytics/event": "_post_analytics",
        "/api/login/request": "_post_login_request",
        "/api/login/verify": "_post_login_verify",
        "/api/merchants/import-demo": "_post_import_demo",
        "/api/admin/merchants": "_post_admin_merchant",
    }

    def do_POST(self):
        try:
            payload = self._read_payload()
        except RequestError as error:
            return self.send_json({"error": error.code}, error.status)
        handler = self.POST_ROUTES.get(self.path)
        if handler is None:
            return self.send_error(404)
        return getattr(self, handler)(payload)

    def _read_payload(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise RequestError("invalid_content_length") from error
        if length < 0:
            raise RequestError("invalid_content_length")
        if length > MAX_REQUEST_BYTES:
            raise RequestError("request_too_large", 413)
        try:
            return JSON_OBJECT.validate_json(self.rfile.read(length))
        except ValidationError as error:
            raise RequestError("invalid_json") from error

    def _post_analytics(self, payload):
        session_id = self.headers.get("X-Kahoo-Session")
        try:
            event = AnalyticsEvent.model_validate({**payload, "session_id": session_id})
        except ValidationError:
            return self.send_json({"saved": False}, 400)
        record_event(event)
        return self.send_json({"saved": True}, 201)

    def _post_login_request(self, payload):
        try:
            login = LoginRequest.model_validate(payload)
        except ValidationError:
            return self.send_json({"error": "invalid_login"}, 400)
        return self.send_json({"challenge_id": str(uuid.uuid4()), "phone": login.phone})

    def _post_login_verify(self, payload):
        try:
            login = LoginVerification.model_validate(payload)
        except ValidationError:
            return self.send_json({"error": "invalid_code"}, 400)
        return self.send_json({"user": {"phone": login.phone, "display_name": "حساب من"}})

    def _post_import_demo(self, _payload):
        return self.send_json(import_demo_merchant(), 201)

    def _post_admin_merchant(self, payload):
        if not admin_mutation_authorized(self.headers):
            return self.send_json(
                {"error": "unauthorized", "message": "کلید مدیریت نادرست است."}, 401
            )
        try:
            request = MerchantImport.model_validate(payload)
        except ValidationError as error:
            return self.send_json({"error": "merchant_import_failed", "message": str(error)}, 400)
        result = add_or_refresh_merchant(request)
        return self.send_json(result, 201 if result.created else 200)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/admin/merchants/"):
            return self.send_error(404)
        if not admin_mutation_authorized(self.headers):
            return self.send_json(
                {"error": "unauthorized", "message": "کلید مدیریت نادرست است."}, 401
            )
        try:
            merchant_id = int(parsed.path.rsplit("/", 1)[1])
        except ValueError:
            return self.send_json({"error": "invalid_merchant_id"}, 400)
        removed = remove_merchant(merchant_id)
        if removed is None:
            return self.send_json({"error": "not_found"}, 404)
        return self.send_json({"removed": removed})
