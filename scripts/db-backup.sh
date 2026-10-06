#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash scripts/db-backup.sh [--directory DIRECTORY]

Create and validate a PostgreSQL custom-format backup of the Compose db service.
The default directory is backups/. Completed archives have private permissions;
failed or incomplete archives are removed. Uses .env.example and .env if present.
HELP
}

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
backup_directory="$project_root/backups"
while (($#)); do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --directory)
      [[ $# -ge 2 && -n "$2" ]] || { usage >&2; exit 2; }
      backup_directory=$2
      shift 2
      ;;
    *) usage >&2; exit 2 ;;
  esac
done

compose=(docker compose --project-directory "$project_root" --env-file "$project_root/.env.example")
if [[ -f "$project_root/.env" ]]; then
  compose+=(--env-file "$project_root/.env")
fi

umask 077
mkdir -p -- "$backup_directory"
temporary_archive=$(mktemp "$backup_directory/.kahoo-backup.XXXXXX")
trap 'rm -f -- "$temporary_archive"' EXIT
"${compose[@]}" exec -T db sh -eu -c \
  'exec pg_dump --no-password --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' \
  > "$temporary_archive"
"${compose[@]}" exec -T db pg_restore --list < "$temporary_archive" > /dev/null
archive="$backup_directory/kahoo-$(date -u +%Y%m%dT%H%M%SZ)-${temporary_archive##*.}.dump"
mv -n -- "$temporary_archive" "$archive"
[[ ! -f "$temporary_archive" ]] || { echo 'Backup filename already exists.' >&2; exit 1; }
printf '%s\n' "$archive"
