from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from backend.config import PROJECT_ROOT, settings

MIGRATIONS_ROOT = PROJECT_ROOT / "db" / "migrations"
# A stable application-specific key shared by schema and category maintenance.
MAINTENANCE_LOCK_ID = 0x4B41484F4F4442


@contextmanager
def connect():
    with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
        yield connection


@contextmanager
def maintenance_connection():
    """Serialize schema/category changes and roll back the entire operation on failure."""
    with connect() as database, database.transaction():
        database.execute("SELECT pg_advisory_xact_lock(%s)", (MAINTENANCE_LOCK_ID,))
        yield database


def apply_migrations(database):
    database.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
             version text PRIMARY KEY,
             applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    applied = {row["version"] for row in database.execute("SELECT version FROM schema_migrations")}
    for path in sorted(MIGRATIONS_ROOT.glob("*.sql")):
        if path.name in applied:
            continue
        database.execute(path.read_text(encoding="utf-8"))
        database.execute(
            "INSERT INTO schema_migrations(version) VALUES(%s)",
            (path.name,),
        )


def run_migrations():
    with maintenance_connection() as database:
        apply_migrations(database)


def apply_category_seed(database, path):
    script = path.read_text(encoding="utf-8")
    script = script.replace("BEGIN;", "", 1).rsplit("COMMIT;", 1)[0]
    database.execute(script)
    return True


def run_category_seed(path):
    with maintenance_connection() as database:
        return apply_category_seed(database, path)


def initialize_database():
    """Apply schema and categories atomically for both server and CLI startup."""
    with maintenance_connection() as database:
        apply_migrations(database)
        seeded = apply_category_seed(database, PROJECT_ROOT / "data/categories.sql")
    return {"migrated": True, "categories_seeded": seeded}
