import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, call, patch

from backend.database import (
    MAINTENANCE_LOCK_ID,
    apply_category_seed,
    initialize_database,
)


class DatabaseMigrationTests(unittest.TestCase):
    def migration_files(self, root):
        migrations = root / "db" / "migrations"
        migrations.mkdir(parents=True)
        (migrations / "002_second.sql").write_text("SECOND MIGRATION;")
        (migrations / "001_first.sql").write_text("FIRST MIGRATION;")
        (root / "data").mkdir()
        seed = root / "data" / "categories.sql"
        seed.write_text("CATEGORY SEED;\n")
        return migrations, seed

    def database(self, connect, applied=(), seed_hash=None):
        database = MagicMock()
        connect.return_value.__enter__.return_value = database

        def execute(sql, params=None):
            result = MagicMock()
            result.fetchone.return_value = {"value": seed_hash} if seed_hash else None
            if sql == "SELECT version,checksum FROM schema_migrations":
                return [{"version": version, "checksum": checksum} for version, checksum in applied]
            return result

        database.execute.side_effect = execute
        return database

    @patch("backend.database.connect")
    def test_initialize_serializes_schema_and_seed_in_one_transaction(self, connect):
        database = self.database(connect)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            migrations, _ = self.migration_files(root)
            with (
                patch("backend.database.PROJECT_ROOT", root),
                patch("backend.database.MIGRATIONS_ROOT", migrations),
            ):
                self.assertEqual(
                    {"migrated": True, "categories_seeded": True}, initialize_database()
                )
        connect.assert_called_once_with()
        database.transaction.assert_called_once_with()
        self.assertEqual(
            call("SELECT pg_advisory_xact_lock(%s)", (MAINTENANCE_LOCK_ID,)),
            database.execute.call_args_list[0],
        )
        database.execute.assert_any_call("FIRST MIGRATION;")
        database.execute.assert_any_call("SECOND MIGRATION;")
        database.execute.assert_any_call("CATEGORY SEED;\n")
        database.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    @patch("backend.database.connect")
    def test_unchanged_migrations_are_not_reexecuted(self, connect):
        checksum = hashlib.sha256(b"FIRST MIGRATION;").hexdigest()
        database = self.database(connect, applied=(("001_first.sql", checksum),))
        with TemporaryDirectory() as directory:
            migrations, _ = self.migration_files(Path(directory))
            with (
                patch("backend.database.MIGRATIONS_ROOT", migrations),
                patch("backend.database.PROJECT_ROOT", Path(directory)),
            ):
                initialize_database()
        self.assertNotIn(call("FIRST MIGRATION;"), database.execute.call_args_list)
        database.execute.assert_any_call("SECOND MIGRATION;")

    @patch("backend.database.connect")
    def test_changed_applied_migration_aborts_the_transaction(self, connect):
        database = self.database(connect, applied=(("001_first.sql", "0" * 64),))
        with TemporaryDirectory() as directory:
            migrations, _ = self.migration_files(Path(directory))
            with (
                patch("backend.database.MIGRATIONS_ROOT", migrations),
                self.assertRaisesRegex(ValueError, "has changed"),
            ):
                initialize_database()
        self.assertNotIn(call("SECOND MIGRATION;"), database.execute.call_args_list)
        self.assertIs(ValueError, database.transaction.return_value.__exit__.call_args.args[0])

    @patch("backend.database.connect")
    def test_legacy_ledger_adopts_checksums_without_reapplying_sql(self, connect):
        database = self.database(connect, applied=(("001_first.sql", None),))
        with TemporaryDirectory() as directory:
            migrations, _ = self.migration_files(Path(directory))
            with (
                patch("backend.database.MIGRATIONS_ROOT", migrations),
                patch("backend.database.PROJECT_ROOT", Path(directory)),
            ):
                initialize_database()
        self.assertNotIn(call("FIRST MIGRATION;"), database.execute.call_args_list)
        self.assertTrue(
            any(
                "UPDATE schema_migrations" in item.args[0]
                for item in database.execute.call_args_list
            )
        )

    @patch("backend.database.connect")
    def test_missing_applied_migration_is_an_error(self, connect):
        self.database(connect, applied=(("099_missing.sql", "0" * 64),))
        with TemporaryDirectory() as directory:
            migrations, _ = self.migration_files(Path(directory))
            with (
                patch("backend.database.MIGRATIONS_ROOT", migrations),
                self.assertRaisesRegex(ValueError, "missing"),
            ):
                initialize_database()

    @patch("backend.database.connect")
    def test_unchanged_category_seed_does_not_rewrite_categories(self, connect):
        checksum = hashlib.sha256(b"CATEGORY SEED;\n").hexdigest()
        database = self.database(connect, seed_hash=checksum)
        with TemporaryDirectory() as directory:
            _, seed = self.migration_files(Path(directory))
            self.assertFalse(apply_category_seed(database, seed))
        self.assertNotIn(call("CATEGORY SEED;\n"), database.execute.call_args_list)

    def test_failed_seed_does_not_record_a_successful_fingerprint(self):
        database = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        database.execute.side_effect = [cursor, RuntimeError("seed failed")]
        with TemporaryDirectory() as directory:
            _, seed = self.migration_files(Path(directory))
            with self.assertRaisesRegex(RuntimeError, "seed failed"):
                apply_category_seed(database, seed)
        self.assertEqual(2, database.execute.call_count)
