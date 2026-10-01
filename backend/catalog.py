import json
from pathlib import Path


REQUIRED_NEW_MERCHANT_FIELDS = {
    "name",
    "description",
    "category_code",
    "city",
}


def load_merchant_catalog(path: Path):
    """Load and validate the reproducible public merchant-data snapshot."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshot_at = payload.get("snapshot_at")
    merchants = payload.get("merchants")
    if not snapshot_at or not isinstance(merchants, list):
        raise ValueError("merchant catalog needs snapshot_at and a merchants list")

    handles = set()
    for merchant in merchants:
        handle = merchant.get("handle", "")
        if not handle.startswith("@") or handle != handle.lower():
            raise ValueError(f"invalid merchant handle: {handle!r}")
        if handle in handles:
            raise ValueError(f"duplicate merchant handle: {handle}")
        handles.add(handle)
        if merchant.get("is_new"):
            missing = REQUIRED_NEW_MERCHANT_FIELDS - merchant.keys()
            if missing:
                raise ValueError(f"{handle} is missing: {', '.join(sorted(missing))}")
        categories = merchant.get("category_codes", [])
        if len(categories) != len(set(categories)):
            raise ValueError(f"duplicate category for {handle}")
        for field in ("followers_count", "media_count"):
            value = merchant.get(field)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"invalid {field} for {handle}")

    return snapshot_at, merchants
