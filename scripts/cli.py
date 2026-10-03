"""One command-line interface for server and maintenance operations."""

import argparse
import json
from pathlib import Path

import psycopg

from backend.database import PROJECT_ROOT
from backend.server.app import serve
from scripts import catalog, categories, database, enrichment, media, merchants, search


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive(value):
    number = nonnegative(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def parser():
    root = argparse.ArgumentParser(
        prog="python -m scripts", description="Kahoo server and maintenance CLI"
    )
    commands = root.add_subparsers(dest="command", required=True)

    def action(parent, name, help_text, handler, needs_db=True):
        command = parent.add_parser(name, help=help_text, description=help_text)
        command.set_defaults(handler=handler, needs_db=needs_db)
        return command

    def group(name, help_text):
        return commands.add_parser(name, help=help_text).add_subparsers(
            dest="action", required=True
        )

    server = action(commands, "serve", "Start the HTTP server", serve, False)
    server.add_argument("--host")
    server.add_argument("--port", type=positive)

    db = group("db", "Database setup and legacy import")
    action(db, "migrate", "Apply migrations and the category seed", database.migrate, False)
    legacy = action(
        db, "import-sqlite", "Import an existing SQLite database", database.import_sqlite, False
    )
    legacy.add_argument("--source", type=Path, required=True)
    legacy.add_argument("--database-url")

    shops = group("merchants", "List, import and remove merchants")
    listing = action(shops, "list", "List stored merchants", merchants.list_merchants)
    listing.add_argument("--query", default="")
    listing.add_argument("--limit", type=positive, default=50)
    listing.add_argument("--offset", type=nonnegative, default=0)
    add = action(shops, "add", "Import a profile; new merchants require --category", merchants.add)
    add.add_argument("identifier", help="username, @username, or Instagram profile URL")
    add.add_argument(
        "--category", help="GPC category code; existing merchants keep their category if omitted"
    )
    add.add_argument("--name")
    add.add_argument("--description")
    add.add_argument("--city", default="ایران")
    remove = action(
        shops, "remove", "Remove a merchant and persist its catalog exclusion", merchants.remove
    )
    remove.add_argument("merchant_id", type=positive)
    batch = action(
        shops,
        "import-file",
        "Import whitespace-separated handles or profile URLs",
        merchants.import_file,
    )
    batch.add_argument("source", type=Path)
    batch.add_argument(
        "--category", help="Required for new merchants; use a separate file for each category"
    )
    batch.add_argument("--city", default="ایران")

    catalogs = group("catalog", "Import reviewed snapshots and build category data")
    seed = action(
        catalogs,
        "import",
        "Import supplied JSON catalogs, or all checked-in snapshots",
        catalog.import_catalog,
    )
    seed.add_argument("paths", nargs="*", type=Path)
    build = action(
        catalogs,
        "build-categories",
        "Build the GS1 category seed from publications",
        categories.build,
        False,
    )
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--persian", type=Path, required=True)
    build.add_argument("--policy", type=Path, default=PROJECT_ROOT / "data/gpc_policy.json")
    build.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/categories.sql")
    build.add_argument("--download", action="store_true")

    images = group("media", "Inspect, synchronize and cache Instagram media")
    status = action(
        images, "status", "Report missing avatars and incomplete galleries", media.status
    )
    sync = action(images, "sync", "Refresh profiles and galleries", media.sync)
    cache = action(
        images, "cache", "Cache uncached post URLs without refreshing profiles", media.cache
    )
    for command in (status, sync, cache):
        command.add_argument(
            "handles", nargs="*", help="Restrict to these handles/profile URLs; defaults to all"
        )
    for command in (status, sync):
        command.add_argument("--minimum-post-images", type=nonnegative, default=3)
    sync.add_argument("--only-missing", action="store_true")
    sync.add_argument("--avatars-only", action="store_true")
    sync.add_argument(
        "--limit", type=nonnegative, default=0, help="Maximum profiles to process; 0 means all"
    )

    index = group("search", "Reindex, evaluate and apply sourced enrichment")
    reindex = action(
        index, "reindex", "Refresh search metadata, documents and embeddings", search.reindex
    )
    reindex.add_argument("--batch-size", type=positive, default=100)
    reindex.add_argument(
        "--all", action="store_true", help="Embed all pending documents in committed batches"
    )
    evaluate = action(
        index, "evaluate", "Run the reviewed search relevance benchmark", search.evaluate
    )
    evaluate.add_argument(
        "--benchmark", type=Path, default=PROJECT_ROOT / "data/search_benchmarks.json"
    )
    enrich = action(
        index,
        "enrich",
        "Apply a JSON description and search terms with provenance",
        enrichment.apply,
    )
    enrich.add_argument("merchant_id", type=positive)
    enrich.add_argument("source", type=Path)
    return root


def main(argv=None):
    command = parser()
    args = command.parse_args(argv)
    try:
        if args.needs_db:
            database.migrate(args)
        result = args.handler(args)
    except (ValueError, OSError, psycopg.Error) as error:
        command.exit(1, f"error: {error}\n")
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if isinstance(result, dict) and result.get("failed") else 0
