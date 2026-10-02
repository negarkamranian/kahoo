#!/usr/bin/env python3
"""Build a deterministic merchant catalog from shared Instagram profile URLs."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
HANDLE_PATTERN = re.compile(r"[a-z0-9._]{1,30}")

# These rules deliberately use broad GPC groups. A later Instagram profile sync
# adds biography and post text that the normal search metadata job can use.
CATEGORY_RULES = (
    ("10000000", "خوراک و لوازم حیوانات خانگی", ("petfood", "pet.")),
    ("53161000", "محصولات آرایشی و زیبایی", ("beauty", "makeup", "cosmetic")),
    ("64010100", "زیورآلات و اکسسوری", ("jewelry", "adorn", "piercing")),
    ("93037400", "گل، گیاه و محصولات گل‌آرایی", ("flower",)),
    ("73040000", "لوازم خانه، دکوراسیون و محصولات هنری", ("room", "gabbeh", "pallet", "antique", "objects", "craft", "artstore")),
    ("70011400", "صنایع دستی و آثار هنری", ("handmade", "craft", "art", "print")),
    ("62060100", "لوازم تحریر، چاپ و استیکر", ("stiker", "sticker", "print")),
    ("64010300", "ساعت و اکسسوری", ("watch",)),
)
DEFAULT_CATEGORY = ("67010000", "پوشاک و اکسسوری مد")


def instagram_handles(text: str):
    handles = []
    seen = set()
    for url in re.findall(r"https?://(?:www\.)?instagram\.com/[^\s]+", text, re.I):
        username = urlparse(url).path.strip("/").split("/", 1)[0].lower()
        if not HANDLE_PATTERN.fullmatch(username):
            raise ValueError(f"invalid Instagram profile URL: {url}")
        if username not in seen:
            seen.add(username)
            handles.append(username)
    return handles


def existing_handles():
    paths = [
        PROJECT_ROOT / "data" / "merchant_catalog.json",
        *sorted((PROJECT_ROOT / "data").glob("merchant_catalog_expansion_*.json")),
    ]
    return {
        merchant["handle"].lstrip("@")
        for path in paths
        for merchant in json.loads(path.read_text(encoding="utf-8"))["merchants"]
    }


def display_name(username: str):
    words = [word for word in re.split(r"[._]+", username.strip("._")) if word]
    return " ".join(word.capitalize() for word in words) or username


def classify(username: str):
    for code, description, keywords in CATEGORY_RULES:
        if any(keyword in username for keyword in keywords):
            return code, description
    return DEFAULT_CATEGORY


def build(source: Path):
    known = existing_handles()
    records = []
    for username in instagram_handles(source.read_text(encoding="utf-8")):
        if username in known:
            continue
        category_code, description = classify(username)
        profile_url = f"https://www.instagram.com/{username}/"
        records.append(
            {
                "handle": f"@{username}",
                "is_new": True,
                "name": display_name(username),
                "description": description,
                "description_source": "user_submitted_profile_url",
                "category_code": category_code,
                "category_codes": [],
                "city": "ایران",
                "source_url": profile_url,
            }
        )
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="text file containing Instagram profile URLs")
    parser.add_argument("--output", type=Path, help="write JSON to this path instead of stdout")
    args = parser.parse_args()
    payload = {
        "version": 1,
        "snapshot_at": "2026-10-02T14:41:00+03:30",
        "notes": "Instagram profiles submitted by the user. Category is inferred conservatively from the handle until profile synchronization succeeds.",
        "merchants": build(args.source),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
