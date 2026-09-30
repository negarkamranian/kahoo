#!/usr/bin/env python3
import argparse
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import connect, run_category_seed, run_migrations
from backend.search import sync_search_documents


TABLES = (
    "categories",
    "category_metadata",
    "merchants",
    "merchant_posts",
    "merchant_categories",
    "merchant_search_terms",
    "search_aliases",
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
    order = " ORDER BY level,id" if table == "categories" and "id" in source_columns else ""
    if table == "categories":
        order = " ORDER BY level,sort_order"
    rows = source.execute(
        f"SELECT {','.join(source_columns)} FROM {table}{order}"
    ).fetchall()
    placeholders = ",".join("%s" for _ in source_columns)
    columns = ",".join(source_columns)
    for row in rows:
        target.execute(
            f"""INSERT INTO {table}({columns}) VALUES({placeholders})
                ON CONFLICT DO NOTHING""",
            tuple(row[column] for column in source_columns),
        )
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Import Kahoo's legacy SQLite database into PostgreSQL")
    parser.add_argument("--source", type=Path, default=PROJECT_ROOT / "data" / "kahoo.db")
    parser.add_argument("--database-url", help="Overrides DATABASE_URL")
    args = parser.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
    if not args.source.is_file():
        parser.error(f"SQLite source does not exist: {args.source}")

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
            sync_search_documents(target)
    finally:
        source.close()

    for table, count in imported.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()
