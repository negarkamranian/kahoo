import os
from contextlib import contextmanager
from pathlib import Path

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_ROOT = PROJECT_ROOT / "db" / "migrations"
DEFAULT_DATABASE_URL = "postgresql://kahoo:kahoo@127.0.0.1:5432/kahoo"


class HybridRow(dict):
    """Mapping row that preserves the small amount of legacy index access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def hybrid_row(cursor):
    columns = [column.name for column in cursor.description]

    def make_row(values):
        return HybridRow(zip(columns, values))

    return make_row


def database_url():
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


class Database:
    def __init__(self, connection):
        self.connection = connection

    @staticmethod
    def translate(query):
        return (query.replace("?", "%s")
                .replace("datetime('now')", "CURRENT_TIMESTAMP")
                .replace("date('now')", "CURRENT_DATE"))

    def execute(self, query, params=None):
        return self.connection.execute(self.translate(query), params)

    def executescript(self, script):
        return self.connection.execute(script)


@contextmanager
def connect():
    with psycopg.connect(database_url(), row_factory=hybrid_row) as connection:
        yield Database(connection)


def run_migrations():
    with psycopg.connect(database_url(), autocommit=True, row_factory=hybrid_row) as database:
        database.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                 version text PRIMARY KEY,
                 applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        applied = {
            row["version"]
            for row in database.execute("SELECT version FROM schema_migrations")
        }
        for path in sorted(MIGRATIONS_ROOT.glob("*.sql")):
            if path.name in applied:
                continue
            with database.transaction():
                database.execute(path.read_text(encoding="utf-8"))
                database.execute(
                    "INSERT INTO schema_migrations(version) VALUES(%s)",
                    (path.name,),
                )


def run_category_seed(path):
    with connect() as database:
        exists = database.execute(
            "SELECT 1 FROM category_metadata WHERE key='gpc_source'"
        ).fetchone()
        if exists:
            return False
        script = path.read_text(encoding="utf-8")
        script = script.replace("BEGIN;", "", 1).rsplit("COMMIT;", 1)[0]
        database.execute(script)
        return True
