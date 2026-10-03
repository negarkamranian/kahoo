#!/usr/bin/env python3
import os
import sqlite3

from backend.database import PROJECT_ROOT, connect, run_category_seed, run_migrations
from backend.search.indexing import sync_search_documents
from backend.search.metadata import sync_search_metadata

TABLES = (
    "categories",
    "category_metadata",
    "merchants",
    "merchant_posts",
    "merchant_categories",
    "merchant_search_terms",
    "analytics_events",
)
SERIAL_TABLES = ("merchants", "merchant_posts", "merchant_search_terms", "analytics_events")


def target_columns(database, table):
    return {
        row["column_name"]
        for row in database.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='public' AND table_name=%s""",
            (table,),
        )
    }


def import_table(source, target, table):
    available = target_columns(target, table)
    source_columns = [
        row["name"]
        for row in source.execute(f"PRAGMA table_info({table})")
        if row["name"] in available
    ]
    if not source_columns:
        return 0
    order = " ORDER BY level,sort_order" if table == "categories" else ""
    rows = source.execute(f"SELECT {','.join(source_columns)} FROM {table}{order}").fetchall()
    placeholders = ",".join("%s" for _ in source_columns)
    columns = ",".join(source_columns)
    for row in rows:
        target.execute(
            f"""INSERT INTO {table}({columns}) VALUES({placeholders})
                ON CONFLICT DO NOTHING""",
            tuple(row[column] for column in source_columns),
        )
    return len(rows)


def import_sqlite(args):
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    if not args.source.is_file():
        raise ValueError(f"SQLite source does not exist: {args.source}")

    run_migrations()
    run_category_seed(PROJECT_ROOT / "data" / "categories.sql")
    source = sqlite3.connect(args.source)
    source.row_factory = sqlite3.Row
    imported = {}
    try:
        with connect() as target:
            for table in TABLES:
                imported[table] = import_table(source, target, table)
            for table in SERIAL_TABLES:
                target.execute(
                    f"""SELECT setval(pg_get_serial_sequence('{table}','id'),
                         COALESCE((SELECT MAX(id) FROM {table}),1),true)"""
                )
            sync_search_metadata(target)
            sync_search_documents(target)
    finally:
        source.close()

    return imported


def migrate(args):
    run_migrations()
    seeded = run_category_seed(PROJECT_ROOT / "data/categories.sql")
    return {"migrated": True, "categories_seeded": seeded}
