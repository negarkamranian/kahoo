import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict

from backend.config import settings

LIBPQ_ENVIRONMENT = {
    "host": "PGHOST",
    "hostaddr": "PGHOSTADDR",
    "port": "PGPORT",
    "dbname": "PGDATABASE",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT",
    "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT",
    "connect_timeout": "PGCONNECT_TIMEOUT",
    "application_name": "PGAPPNAME",
    "options": "PGOPTIONS",
    "service": "PGSERVICE",
    "passfile": "PGPASSFILE",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
    "channel_binding": "PGCHANNELBINDING",
}


def database_environment():
    parameters = conninfo_to_dict(settings.database_url)
    if not parameters.get("dbname"):
        raise ValueError("DATABASE_URL must name a database")
    unsupported = parameters.keys() - LIBPQ_ENVIRONMENT.keys()
    if unsupported:
        raise ValueError(
            f"Unsupported archive connection options: {', '.join(sorted(unsupported))}"
        )
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update({LIBPQ_ENVIRONMENT[key]: value for key, value in parameters.items()})
    return environment


def run_tool(arguments, environment, *, stdin=None, stdout=subprocess.DEVNULL):
    subprocess.run(arguments, env=environment, stdin=stdin, stdout=stdout, check=True)


def backup_database(directory):
    environment = database_environment()
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = directory / f"kahoo-{stamp}-{uuid4().hex}.dump"
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".kahoo-", delete=False) as output:
        temporary = Path(output.name)
    try:
        with temporary.open("wb") as output:
            run_tool(["pg_dump", "--no-password", "--format=custom"], environment, stdout=output)
        with temporary.open("rb") as source:
            run_tool(["pg_restore", "--list"], environment, stdin=source)
        os.link(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return {"archive": str(archive)}


def restore_database(archive, target):
    environment = database_environment()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", target):
        raise ValueError("Target database must be a valid PostgreSQL identifier")
    if target == environment.get("PGDATABASE"):
        raise ValueError("Refusing to restore into the current application database")
    with Path(archive).open("rb") as source:
        run_tool(["pg_restore", "--list"], environment, stdin=source)
        run_tool(["createdb", "--no-password", "--", target], environment)
        source.seek(0)
        try:
            run_tool(
                [
                    "pg_restore",
                    "--no-password",
                    "--dbname",
                    target,
                    "--exit-on-error",
                    "--single-transaction",
                    "--no-owner",
                ],
                environment,
                stdin=source,
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"Restore failed; database {target} was left in place for inspection"
            ) from error
    return {"archive": str(Path(archive).resolve()), "database": target}
