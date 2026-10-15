"""One command-line interface for server and maintenance operations."""

import argparse
from importlib import import_module
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from backend.config import PROJECT_ROOT, settings
from backend.database import initialize_database
from backend.models.media import MINIMUM_POST_IMAGES
from backend.models.merchants import AdminMerchantQuery, MerchantImport, MerchantPageSize


def merchant_page_size(value):
    try:
        return TypeAdapter(MerchantPageSize).validate_python(int(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be between 1 and 100") from error


def nonnegative_integer(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer at least 0") from error
    if number < 0:
        raise argparse.ArgumentTypeError("must be an integer at least 0")
    return number


def positive_integer(value):
    number = nonnegative_integer(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be an integer at least 1")
    return number


def port_number(value):
    number = positive_integer(value)
    if number > 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return number


def action(parent, name, help_text, handler, needs_db=True):
    command = parent.add_parser(name, help=help_text, description=help_text)
    command.set_defaults(handler=handler, needs_db=needs_db)
    return command


def group(commands, name, help_text):
    return commands.add_parser(name, help=help_text).add_subparsers(dest="action", required=True)


def register_server(commands):
    server = action(commands, "serve", "Start the HTTP server", "backend.server.app.serve", False)
    server.add_argument("--host", default=settings.host)
    server.add_argument("--port", type=port_number, default=settings.port)


def register_database(commands):
    db = group(commands, "db", "Apply database migrations")
    action(db, "migrate", "Apply migrations and the category seed", "backend.cli.migrate", False)


def register_instagram(commands):
    commands = group(commands, "instagram", "Configure Instagram authorization")
    action(
        commands,
        "generate-key",
        "Generate a new token encryption key",
        "backend.cli.instagram.generate_key",
        False,
    )
    action(
        commands,
        "status",
        "Check authorization configuration without exposing credentials",
        "backend.cli.instagram.status",
        False,
    )


def register_merchants(commands):
    merchant_defaults = AdminMerchantQuery()
    default_city = MerchantImport.model_fields["city"].default  # pylint: disable=unsubscriptable-object
    shops = group(commands, "merchants", "List, import and remove merchants")
    listing = action(shops, "list", "List stored merchants", "backend.cli.merchants.list_merchants")
    listing.add_argument("--query", default="")
    listing.add_argument("--limit", type=merchant_page_size, default=merchant_defaults.limit)
    listing.add_argument("--offset", type=nonnegative_integer, default=merchant_defaults.offset)
    add = action(
        shops,
        "add",
        "Import a profile; new merchants require --category",
        "backend.cli.merchants.add",
    )
    add.add_argument("identifier", help="Instagram handle in @username format")
    add.add_argument(
        "--category", help="GPC category code; existing merchants keep their category if omitted"
    )
    add.add_argument("--city", default=default_city)
    remove = action(
        shops,
        "remove",
        "Remove a merchant and persist its catalog exclusion",
        "backend.cli.merchants.remove",
    )
    remove.add_argument("merchant_id", type=positive_integer)
    batch = action(
        shops,
        "import-file",
        "Import whitespace-separated @username handles",
        "backend.cli.merchants.import_file",
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
        "backend.cli.catalog.import_snapshots",
    )
    seed.add_argument("paths", nargs="*", type=Path)
    build = action(
        catalogs,
        "build-categories",
        "Build the GS1 category seed from publications",
        "backend.cli.catalog.build",
        False,
    )
    build.add_argument("--current", type=Path, required=True)
    build.add_argument("--persian", type=Path, required=True)
    build.add_argument("--policy", type=Path, default=PROJECT_ROOT / "data/gpc_policy.json")
    build.add_argument("--output", type=Path, default=PROJECT_ROOT / "data/categories.sql")
    build.add_argument("--download", action="store_true")
    register_taxonomy(catalogs)


def register_taxonomy(catalogs):
    sync = action(
        catalogs,
        "sync-shopify",
        "Import Shopify 2026-08 product taxonomy into PostgreSQL",
        "backend.cli.taxonomy.sync",
    )
    sync.add_argument("--source", type=Path, help="Use an upstream JSON or JSON.gz file offline")
    sync.add_argument("--license", type=Path, help="Use a local upstream LICENSE file offline")


def register_media(commands):
    images = group(commands, "media", "Inspect, synchronize and cache Instagram media")
    status = action(
        images,
        "status",
        "Report missing avatars and incomplete galleries",
        "backend.cli.media.status",
    )
    sync = action(images, "sync", "Refresh profiles and galleries", "backend.cli.media.sync")
    cache = action(
        images,
        "cache",
        "Cache uncached post URLs without refreshing profiles",
        "backend.cli.media.cache",
    )
    for command in (status, sync, cache):
        command.add_argument(
            "handles", nargs="*", help="Restrict to these @username handles; defaults to all"
        )
    for command in (status, sync):
        command.add_argument(
            "--minimum-post-images", type=positive_integer, default=MINIMUM_POST_IMAGES
        )
    sync.add_argument("--only-missing", action="store_true")
    sync.add_argument("--avatars-only", action="store_true")
    sync.add_argument(
        "--limit",
        type=nonnegative_integer,
        default=0,
        help="Maximum profiles to process; 0 means all",
    )


def register_search(commands):
    index = group(commands, "search", "Reindex and apply sourced enrichment")
    reindex = action(
        index,
        "reindex",
        "Refresh search metadata, documents and embeddings",
        "backend.cli.search.reindex",
    )
    reindex.add_argument("--batch-size", type=positive_integer, default=100)
    reindex.add_argument(
        "--all", action="store_true", help="Embed all pending documents in committed batches"
    )
    register_enrichment(index)


def register_enrichment(index):
    enrich = action(
        index,
        "enrich",
        "Apply a JSON description and search terms with provenance",
        "backend.cli.search.enrich",
    )
    enrich.add_argument("merchant_id", type=positive_integer)
    enrich.add_argument("source", type=Path)
    batch = action(
        index,
        "enrich-file",
        "Atomically apply a researched enrichment batch matched by Instagram handle",
        "backend.cli.search.enrich_file",
    )
    batch.add_argument("source", type=Path)


def register_products(commands):
    commands = group(commands, "products", "Classify Instagram products and extract attributes")
    action(
        commands,
        "enqueue",
        "Queue existing Instagram post collections",
        "backend.cli.products.enqueue",
    )
    worker = action(
        commands, "worker", "Process the durable product queue", "backend.cli.products.worker"
    )
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--limit", type=positive_integer, default=50)
    worker.add_argument("--poll-seconds", type=positive_integer, default=5)


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
        register_products,
        register_instagram,
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
    module_name, function_name = args.handler.rsplit(".", 1)
    handler = getattr(import_module(module_name), function_name)
    result = handler(args)
    if result is not None:
        print(TypeAdapter(Any).dump_json(result, indent=2).decode("utf-8"))
    return 0
