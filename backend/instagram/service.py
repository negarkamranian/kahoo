"""Select the configured Instagram profile source."""

from backend.instagram.embed import public_embed_profile
from backend.instagram.meta import business_discovery_enabled, business_discovery_profile
from backend.models.media import InstagramProfile


def instagram_profile(handle: str) -> InstagramProfile:
    if business_discovery_enabled():
        return business_discovery_profile(handle)
    return public_embed_profile(handle)
