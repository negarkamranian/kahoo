# Kahoo

Persian RTL marketplace for discovering Instagram shops and saving products.

## Run

```bash
cp .env.example .env
# Edit .env, then start:
docker compose --env-file .env.example --env-file .env up --build -d
```

[Marketplace](http://localhost:4173) · [Admin](http://localhost:4173/admin.html) · [Saved items](http://localhost:4173/saved.html) · [API docs](http://localhost:4173/docs)

Startup applies database migrations and seeds categories. Import the catalog and fetch images separately:

```bash
docker compose --env-file .env.example --env-file .env exec app python3 -m backend catalog import
docker compose --env-file .env.example --env-file .env exec app python3 -m backend media sync --only-missing --limit 25
```

## Configuration

Defaults are in [.env.example](.env.example); override them in `.env` and restart.

- `KAHOO_ADMIN_TOKEN`: protects admin mutations; empty means unlocked.
- `META_IG_USER_ID` / `META_ACCESS_TOKEN`: optional Meta integration; otherwise uses public Instagram embeds.
- `EMBEDDING_API_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`: optional semantic search.

Phone login is a demo without SMS verification.

## Development

Python 3.13 and Node.js 22.13+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci
make check
```

`make format` formats code. Run `.venv/bin/python -m backend --help` for CLI commands; in Docker, use the Compose `exec app` prefix above.

Backend: `backend/` · Frontend: `public/` · Migrations: `db/migrations/` · [Search design](system_design_documents/search-core-flow.md)

## Data

PostgreSQL persists in the `kahoo-postgres` volume. Back up with `make db-backup` before upgrades or bulk imports. `docker compose down -v` deletes this data.

Restore into a fresh database:

```bash
make db-restore RESTORE_DB=kahoo_restore_check BACKUP_FILE=backups/ARCHIVE.dump
```
