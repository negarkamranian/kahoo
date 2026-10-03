"""Canonical Instagram URL construction and post identity parsing."""

from urllib.parse import urlparse


def profile_url(handle: str) -> str:
    return f"https://www.instagram.com/{handle[1:]}/"


def post_url(shortcode: str) -> str:
    return f"https://www.instagram.com/p/{shortcode}/"


def instagram_shortcode(permalink: str | None) -> str:
    parts = urlparse(permalink or "").path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"p", "reel"}:
        return parts[1]
    return ""
