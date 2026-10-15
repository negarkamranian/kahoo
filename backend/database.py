import hashlib
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from backend.config import PROJECT_ROOT, settings

MIGRATIONS_ROOT = PROJECT_ROOT / "db" / "migrations"
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
             applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
             checksum text
           )"""
    )
    database.execute("ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum text")
    applied = {
        row["version"]: row["checksum"]
        for row in database.execute("SELECT version,checksum FROM schema_migrations")
    }
    paths = sorted(MIGRATIONS_ROOT.glob("*.sql"))
    missing = applied.keys() - {path.name for path in paths}
    if missing:
        raise ValueError(f"Applied migrations are missing: {', '.join(sorted(missing))}")
    for path in paths:
        apply_migration(database, path, applied)


def apply_migration(database, path, applied):
    content = path.read_bytes()
    checksum = hashlib.sha256(content).hexdigest()
    if path.name not in applied:
        database.execute(content.decode("utf-8"))
        database.execute(
            "INSERT INTO schema_migrations(version,checksum) VALUES(%s,%s)",
            (path.name, checksum),
        )
    elif applied[path.name] is None:
        database.execute(
            "UPDATE schema_migrations SET checksum=%s WHERE version=%s", (checksum, path.name)
        )
    elif applied[path.name] != checksum:
        raise ValueError(f"Applied migration has changed: {path.name}")


def apply_category_seed(database, path):
    script = path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(script.encode("utf-8")).hexdigest()
    previous = database.execute(
        "SELECT value FROM category_metadata WHERE key='gpc_seed_sha256'"
    ).fetchone()
    if previous and previous["value"] == checksum:
        return False
    database.execute(script)
    database.execute(
        """INSERT INTO category_metadata(key,value) VALUES('gpc_seed_sha256',%s)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
        (checksum,),
    )
    return True


def initialize_database():
    """Apply schema and categories atomically for both server and CLI startup."""
    with maintenance_connection() as database:
        apply_migrations(database)
        seeded = apply_category_seed(database, PROJECT_ROOT / "data/categories.sql")
    return {"migrated": True, "categories_seeded": seeded}
