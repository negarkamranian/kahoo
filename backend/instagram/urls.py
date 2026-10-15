"""Canonical Instagram URLs."""


def profile_url(handle: str) -> str:
    return f"https://www.instagram.com/{handle[1:]}/"


def post_url(shortcode: str) -> str:
    return f"https://www.instagram.com/p/{shortcode}/"
