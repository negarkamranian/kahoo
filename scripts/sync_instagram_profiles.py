#!/usr/bin/env python3
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import run_category_seed, run_migrations
from backend.server import DATA_ROOT, refresh_instagram_profiles

if __name__ == "__main__":
    run_migrations()
    run_category_seed(DATA_ROOT / "categories.sql")

    def show_profile(result):
        if result["updated"]:
            print(
                f"{result['handle']}: {result['posts_found']} posts, "
                f"{result['images_saved']} images saved",
                flush=True,
            )
        else:
            print(f"{result['handle']}: FAILED - {result['error']}", flush=True)

    print(
        json.dumps(
            refresh_instagram_profiles(sys.argv[1:], on_result=show_profile),
            ensure_ascii=False,
            indent=2,
        )
    )
