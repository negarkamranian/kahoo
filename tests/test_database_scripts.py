import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FAKE_DATABASE_TOOLS = r"""
import json
import os
import subprocess
import sys
from pathlib import Path

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FAKE_DATABASE_LOG"], "a") as output:
    output.write(json.dumps([tool, *args]) + "\n")
if tool == "docker":
    start = args.index("db") + 1
    raise SystemExit(subprocess.run(args[start:], check=False).returncode)
if tool == "pg_dump":
    sys.stdout.buffer.write(b"PGDMP: test archive")
    raise SystemExit(1 if os.environ.get("FAIL_DUMP") else 0)
if tool == "createdb":
    raise SystemExit(1 if args[-1] == "existing" else 0)
if tool == "pg_restore":
    archive = sys.stdin.buffer.read()
    invalid = not archive.startswith(b"PGDMP") or os.environ.get("FAIL_VALIDATION")
    failed = "--list" not in args and os.environ.get("FAIL_RESTORE")
    raise SystemExit(1 if invalid or failed else 0)
raise SystemExit(2)
"""


class DatabaseScriptTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        tools = self.root / "bin"
        tools.mkdir()
        for name in ("docker", "pg_dump", "pg_restore", "createdb"):
            executable = tools / name
            executable.write_text(f"#!{sys.executable}\n{FAKE_DATABASE_TOOLS}")
            executable.chmod(0o700)
        self.log = self.root / "commands.jsonl"
        self.environment = {
            **os.environ,
            "PATH": f"{tools}:{os.defpath}",
            "POSTGRES_USER": "test_user",
            "POSTGRES_DB": "live",
            "FAKE_DATABASE_LOG": str(self.log),
        }
        self.archive = self.root / "source.dump"
        self.archive.write_bytes(b"PGDMP: test archive")

    def run_script(self, script, *arguments, **environment):
        return subprocess.run(
            ["bash", str(PROJECT_ROOT / "scripts" / script), *map(str, arguments)],
            env={**self.environment, **environment},
            capture_output=True,
            text=True,
            check=False,
        )

    def commands(self, tool):
        rows = self.log.read_text().splitlines() if self.log.exists() else []
        return [row for line in rows if (row := json.loads(line))[0] == tool]

    def test_help_needs_no_docker_or_database(self):
        for script in ("db-backup.sh", "db-restore.sh"):
            with self.subTest(script=script):
                result = self.run_script(script, "--help")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("Usage:", result.stdout)
        self.assertFalse(self.log.exists())

    def test_backup_is_private_and_visible_only_after_validation(self):
        backups = self.root / "backups"
        result = self.run_script("db-backup.sh", "--directory", backups)
        self.assertEqual(0, result.returncode, result.stderr)
        archive = Path(result.stdout.strip())
        self.assertEqual(backups, archive.parent)
        self.assertEqual(b"PGDMP: test archive", archive.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(archive.stat().st_mode))
        self.assertEqual([archive], list(backups.iterdir()))
        self.assertIn("--format=custom", self.commands("pg_dump")[0])
        self.assertEqual(["pg_restore", "--list"], self.commands("pg_restore")[0])
        for command in self.commands("docker"):
            self.assertIn("--env-file", command)
            self.assertIn(str(PROJECT_ROOT / ".env.example"), command)

    def test_failed_dump_or_validation_leaves_no_archive(self):
        for failure in ("FAIL_DUMP", "FAIL_VALIDATION"):
            with self.subTest(failure=failure):
                backups = self.root / failure
                result = self.run_script("db-backup.sh", "--directory", backups, **{failure: "1"})
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], list(backups.iterdir()))

    def test_restore_requires_a_target_and_refuses_the_live_or_existing_database(self):
        for arguments in (
            [self.archive],
            ["--database", "live", self.archive],
            ["--database", "existing", self.archive],
            ["--database", "bad-name", self.archive],
        ):
            with self.subTest(arguments=arguments):
                result = self.run_script("db-restore.sh", *arguments)
                self.assertNotEqual(0, result.returncode)
        self.assertEqual([], [row for row in self.commands("pg_restore") if "--list" not in row])
        self.assertEqual(["existing"], [row[-1] for row in self.commands("createdb")])

    def test_restore_validates_archive_and_uses_one_transaction_in_new_database(self):
        result = self.run_script("db-restore.sh", "--database", "restore_test", self.archive)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("restore_test", self.commands("createdb")[0][-1])
        restore = self.commands("pg_restore")[1]
        for option in ("--single-transaction", "--exit-on-error", "--no-owner", "--no-password"):
            self.assertIn(option, restore)
        self.assertEqual("restore_test", restore[restore.index("--dbname") + 1])

    def test_invalid_archive_never_creates_a_database(self):
        self.archive.write_bytes(b"invalid")
        result = self.run_script("db-restore.sh", "--database", "restore_test", self.archive)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self.commands("createdb"))

    def test_restore_failure_is_reported_without_attempting_a_second_restore(self):
        result = self.run_script(
            "db-restore.sh", "--database", "restore_test", self.archive, FAIL_RESTORE="1"
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("left in place", result.stderr)
        self.assertEqual(2, len(self.commands("pg_restore")))
