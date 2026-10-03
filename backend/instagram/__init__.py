"""Select the configured Instagram profile source."""

from backend.instagram.embed import extract_embed_posts, public_embed_profile
from backend.instagram.meta import business_discovery_enabled, business_discovery_profile
from backend.instagram_urls import instagram_shortcode
from backend.models.media import InstagramProfile

__all__ = [
    "business_discovery_enabled",
    "business_discovery_profile",
    "extract_embed_posts",
    "instagram_profile",
    "instagram_shortcode",
    "public_embed_profile",
]


def instagram_profile(handle: str) -> InstagramProfile:
    if business_discovery_enabled():
        return business_discovery_profile(handle)
    return public_embed_profile(handle)
