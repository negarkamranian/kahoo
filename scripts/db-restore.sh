#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash scripts/db-restore.sh --database NEW_DATABASE BACKUP_FILE

Validate and restore a PostgreSQL archive into a newly created database in the
Compose db service. Refuses the current POSTGRES_DB and existing target names.
The restore is one transaction; a failed restore leaves the new database empty.
Uses .env.example and .env if present. It does not switch the application's URL.
HELP
}

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
restore_database=""
archive=""
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --database)
      [[ $# -ge 2 && -z "$restore_database" ]] || { usage >&2; exit 2; }
      restore_database=$2
      shift 2
      ;;
    --*) usage >&2; exit 2 ;;
    *)
      [[ -z "$archive" ]] || { usage >&2; exit 2; }
      archive=$1
      shift
      ;;
  esac
done
[[ "$restore_database" =~ ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ ]] || {
  echo 'Specify --database with a new name containing letters, numbers, or underscores.' >&2
  exit 2
}
[[ -f "$archive" && -r "$archive" ]] || { echo 'A readable backup file is required.' >&2; exit 2; }

compose=(docker compose --project-directory "$project_root" --env-file "$project_root/.env.example")
if [[ -f "$project_root/.env" ]]; then
  compose+=(--env-file "$project_root/.env")
fi

"${compose[@]}" exec -T db pg_restore --list < "$archive" > /dev/null
"${compose[@]}" exec -T db sh -eu -c '
  target=$1
  if [ "$target" = "$POSTGRES_DB" ]; then
    echo "Refusing to restore into the current application database." >&2
    exit 2
  fi
  exec createdb --no-password --username "$POSTGRES_USER" --maintenance-db "$POSTGRES_DB" -- "$target"
' sh "$restore_database"
if ! "${compose[@]}" exec -T db sh -eu -c \
  'exec pg_restore --no-password --username "$POSTGRES_USER" --dbname "$1" --exit-on-error --single-transaction --no-owner' \
  sh "$restore_database" < "$archive"; then
  printf 'Restore failed; the new database %s was left in place for inspection.\n' "$restore_database" >&2
  exit 1
fi
printf 'Restored %s into new database %s.\n' "$archive" "$restore_database"
