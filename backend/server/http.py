import hmac
import json
import logging
import mimetypes
import os
import uuid
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from backend.database import PROJECT_ROOT, connect
from backend.search.service import merchants
from backend.search.suggestions import search_suggestions
from backend.server.analytics import admin_metrics, record_event
from backend.server.categories import category_tree
from backend.server.merchants import admin_merchants, merchant_detail, remove_merchant
from scripts.merchants import add_or_refresh_merchant

PUBLIC_ROOT = PROJECT_ROOT / "public"
logger = logging.getLogger(__name__)


def admin_mutation_authorized(headers):
    configured = os.environ.get("KAHOO_ADMIN_TOKEN", "")
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
        body = json.dumps(
            payload,
            ensure_ascii=False,
            default=lambda value: (
                value.isoformat()
                if isinstance(value, (date, datetime))
                else float(value)
                if isinstance(value, Decimal)
                else str(value)
            ),
        ).encode()
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/categories":
            return self.send_json(category_tree())
        if parsed.path == "/api/search/suggestions":
            args = parse_qs(parsed.query)
            return self.send_json(search_suggestions(args.get("q", [""])[0]))
        if parsed.path == "/api/merchants":
            args = parse_qs(parsed.query)
            category = args.get("category", [None])[0]
            query = args.get("q", [""])[0]
            result = merchants(category, query)
            session_id = self.headers.get("X-Kahoo-Session")
            if query:
                record_event(
                    "search",
                    session_id,
                    query=query,
                    category_code=category,
                    result_count=len(result),
                )
            elif category:
                record_event(
                    "category_view", session_id, category_code=category, result_count=len(result)
                )
            return self.send_json(result)
        if parsed.path.startswith("/api/merchants/"):
            try:
                merchant_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                return self.send_error(404)
            result = merchant_detail(merchant_id)
            return self.send_json(result) if result else self.send_error(404)
        if parsed.path == "/api/admin/metrics":
            args = parse_qs(parsed.query)
            try:
                days = int(args.get("days", [30])[0])
            except ValueError:
                days = 30
            return self.send_json(admin_metrics(days))
        if parsed.path == "/api/admin/merchants":
            args = parse_qs(parsed.query)
            try:
                limit = int(args.get("limit", [50])[0])
                offset = int(args.get("offset", [0])[0])
            except ValueError:
                return self.send_json({"error": "invalid_pagination"}, 400)
            return self.send_json(admin_merchants(args.get("q", [""])[0], limit, offset))
        if parsed.path.startswith("/api/media/"):
            try:
                post_id = int(parsed.path.rsplit("/", 1)[1])
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
        if parsed.path.startswith("/api/avatars/"):
            try:
                merchant_id = int(parsed.path.rsplit("/", 1)[1])
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
        path = PUBLIC_ROOT / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        if not path.is_file() or PUBLIC_ROOT not in path.resolve().parents:
            return self.send_error(404)
        self.send_bytes(
            path.read_bytes(), mimetypes.guess_type(path)[0] or "application/octet-stream"
        )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json({"error": "invalid_content_length"}, 400)
        if length < 0:
            return self.send_json({"error": "invalid_content_length"}, 400)
        if length > 1_048_576:
            return self.send_json({"error": "request_too_large"}, 413)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json({"error": "invalid_json"}, 400)
        if not isinstance(payload, dict):
            return self.send_json({"error": "invalid_json"}, 400)
        if self.path == "/api/analytics/event":
            session_id = self.headers.get("X-Kahoo-Session") or payload.get("session_id")
            saved = record_event(
                payload.get("event_type"),
                session_id,
                payload.get("query"),
                payload.get("category_code"),
                payload.get("merchant_id"),
                payload.get("result_count"),
            )
            return self.send_json({"saved": saved}, 201 if saved else 400)
        if self.path == "/api/login/request":
            return self.send_json(
                {"challenge_id": str(uuid.uuid4()), "phone": payload.get("phone")}
            )
        if self.path == "/api/login/verify":
            if len(str(payload.get("code", ""))) != 5:
                return self.send_json({"error": "invalid_code"}, 400)
            return self.send_json(
                {"user": {"phone": payload.get("phone"), "display_name": "حساب من"}}
            )
        if self.path == "/api/merchants/import-demo":
            return self.send_json(import_demo_merchant(), 201)
        if self.path == "/api/admin/merchants":
            if not admin_mutation_authorized(self.headers):
                return self.send_json(
                    {"error": "unauthorized", "message": "کلید مدیریت نادرست است."}, 401
                )
            try:
                result = add_or_refresh_merchant(
                    payload.get("identifier"),
                    payload.get("category_code"),
                    payload.get("name"),
                    payload.get("description"),
                    payload.get("city", "ایران"),
                )
            except ValueError as error:
                return self.send_json(
                    {"error": "merchant_import_failed", "message": str(error)}, 400
                )
            except Exception:
                logger.exception("Merchant import failed")
                return self.send_json(
                    {"error": "merchant_import_failed", "message": "ذخیره فروشگاه ممکن نشد."}, 500
                )
            return self.send_json(result, 201 if result["created"] else 200)
        return self.send_error(404)

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
        return (
            self.send_json({"removed": removed})
            if removed
            else self.send_json({"error": "not_found"}, 404)
        )
