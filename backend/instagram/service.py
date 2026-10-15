"""Select the configured Instagram profile source."""

from backend.instagram.embed import public_embed_profile
from backend.instagram.meta import business_discovery_enabled, business_discovery_profile
from backend.models.media import InstagramProfile
from backend.services.instagram_credentials import connected_profile


def instagram_profile(handle: str, *, existing_name: str | None = None) -> InstagramProfile:
    connected = connected_profile(handle)
    if connected is not None:
        return connected
    if business_discovery_enabled():
        return business_discovery_profile(handle)
    return public_embed_profile(handle, existing_name=existing_name)
