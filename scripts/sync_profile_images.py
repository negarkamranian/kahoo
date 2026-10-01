#!/usr/bin/env python3
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import run_migrations
from backend.server import refresh_instagram_avatars


def main():
    run_migrations()
    profiles = refresh_instagram_avatars(sys.argv[1:])
    updated = [profile for profile in profiles if profile["updated"]]
    print(json.dumps({
        "profiles_attempted": len(profiles),
        "profile_images_updated": len(updated),
        "profiles_failed": len(profiles) - len(updated),
        "profiles": profiles,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
