#!/usr/bin/env python3
import json
import sys
from pathlib import Path

PROJECT_ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(PROJECT_ROOT))

from backend.server import initialize_database, refresh_instagram_profiles

if __name__=="__main__":
    initialize_database()
    print(json.dumps(refresh_instagram_profiles(sys.argv[1:]),ensure_ascii=False,indent=2))
