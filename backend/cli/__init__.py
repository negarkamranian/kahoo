"""One command-line interface for server and maintenance operations."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from backend.cli import catalog, media, merchants, search
from backend.config import PROJECT_ROOT, settings
from backend.database import initialize_database
from backend.models.media import MINIMUM_POST_IMAGES
from backend.models.merchants import AdminMerchantQuery, MerchantImport, MerchantPageSize
from backend.serialization import json_default
from backend.server.app import serve


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


def merchant_page_size(value):
    try:
        return TypeAdapter(MerchantPageSize).validate_python(int(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be between 1 and 100") from error


def action(parent, name, help_text, handler, needs_db=True):
    command = parent.add_parser(name, help=help_text, description=help_text)
    command.set_defaults(handler=handler, needs_db=needs_db)
    return command


def group(commands, name, help_text):
    return commands.add_parser(name, help=help_text).add_subparsers(dest="action", required=True)


def register_server(commands):
    server = action(commands, "serve", "Start the HTTP server", serve, False)
    server.add_argument("--host", default=settings.host)
    server.add_argument("--port", type=positive, default=settings.port)


def register_database(commands):
    db = group(commands, "db", "Database setup")
    action(db, "migrate", "Apply migrations and the category seed", migrate, False)


def register_merchants(commands):
    merchant_defaults = AdminMerchantQuery()
    default_city = MerchantImport.model_fields["city"].default  # pylint: disable=unsubscriptable-object
    shops = group(commands, "merchants", "List, import and remove merchants")
    listing = action(shops, "list", "List stored merchants", merchants.list_merchants)
    listing.add_argument("--query", default="")
    listing.add_argument("--limit", type=merchant_page_size, default=merchant_defaults.limit)
    listing.add_argument("--offset", type=nonnegative, default=merchant_defaults.offset)
    add = action(shops, "add", "Import a profile; new merchants require --category", merchants.add)
    add.add_argument("identifier", help="Instagram handle in @username format")
    add.add_argument(
        "--category", help="GPC category code; existing merchants keep their category if omitted"
    )
    add.add_argument("--city", default=default_city)
    remove = action(
        shops, "remove", "Remove a merchant and persist its catalog exclusion", merchants.remove
    )
    remove.add_argument("merchant_id", type=positive)
    batch = action(
        shops,
        "import-file",
        "Import whitespace-separated @username handles",
        merchants.import_file,
    )
    batch.add_argument("source", type=Path)
    batch.add_argument(
        "--category", help="Required for new merchants; use a separate file for each category"
    )
    batch.add_argument("--city", default=default_city)


def register_catalog(commands):
    catalogs = group(commands, "catalog", "Import reviewed snapshots and build category data")
    seed = action(
        catalogs,
        "import",
        "Import supplied JSON catalogs, or all checked-in snapshots",
        catalog.import_snapshots,
    )
    seed.add_argument("paths", nargs="*", type=Path)
    build = action(
        catalogs,
        "build-categories",
        "Build the GS1 category seed from publications",
        catalog.build,
        False,
    )
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--persian", type=Path, required=True)
    build.add_argument("--policy", type=Path, default=PROJECT_ROOT / "data/gpc_policy.json")
    build.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/categories.sql")
    build.add_argument("--download", action="store_true")


def register_media(commands):
    images = group(commands, "media", "Inspect, synchronize and cache Instagram media")
    status = action(
        images, "status", "Report missing avatars and incomplete galleries", media.status
    )
    sync = action(images, "sync", "Refresh profiles and galleries", media.sync)
    cache = action(
        images, "cache", "Cache uncached post URLs without refreshing profiles", media.cache
    )
    for command in (status, sync, cache):
        command.add_argument(
            "handles", nargs="*", help="Restrict to these @username handles; defaults to all"
        )
    for command in (status, sync):
        command.add_argument("--minimum-post-images", type=nonnegative, default=MINIMUM_POST_IMAGES)
    sync.add_argument("--only-missing", action="store_true")
    sync.add_argument("--avatars-only", action="store_true")
    sync.add_argument(
        "--limit", type=nonnegative, default=0, help="Maximum profiles to process; 0 means all"
    )


def register_search(commands):
    index = group(commands, "search", "Reindex, evaluate and apply sourced enrichment")
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
        search.enrich,
    )
    enrich.add_argument("merchant_id", type=positive)
    enrich.add_argument("source", type=Path)


def parser():
    root = argparse.ArgumentParser(
        prog="python -m backend", description="Kahoo server and maintenance CLI"
    )
    commands = root.add_subparsers(dest="command", required=True)
    for register in (
        register_server,
        register_database,
        register_merchants,
        register_catalog,
        register_media,
        register_search,
    ):
        register(commands)
    return root


def migrate(_args):
    return initialize_database()


def main(argv=None):
    command = parser()
    args = command.parse_args(argv)
    if args.needs_db:
        initialize_database()
    result = args.handler(args)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))
    return 0
