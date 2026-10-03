#!/usr/bin/env python3
"""Add or refresh one Instagram shop by its public handle or profile URL."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import run_category_seed, run_migrations
from backend.server import DATA_ROOT, add_or_refresh_merchant


def parser():
    command = argparse.ArgumentParser(
        description="Add or refresh a shop from its public Instagram account."
    )
    command.add_argument("identifier", help="username, @username, or Instagram profile URL")
    command.add_argument("--category", help="GPC category code; inferred when omitted")
    command.add_argument("--name", help="merchant display name; Instagram name is used by default")
    command.add_argument(
        "--description",
        help="merchant description; generated from the inferred category by default",
    )
    command.add_argument("--city", default="ایران", help="merchant city (default: ایران)")
    return command


def main():
    args = parser().parse_args()
    run_migrations()
    run_category_seed(DATA_ROOT / "categories.sql")
    try:
        result = add_or_refresh_merchant(
            args.identifier,
            category_code=args.category,
            name=args.name,
            description=args.description,
            city=args.city,
        )
    except ValueError as error:
        parser().error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
