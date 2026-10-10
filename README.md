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

## Connect a shop with Instagram

The store connection button uses real **Instagram Login** for Business and Creator
accounts, requesting only `instagram_business_basic`. It imports the authorized
account's profile and latest posts, including carousel images and video thumbnails.
It does not use the manually configured Business Discovery token.

In your Meta app, enable **Instagram → API setup with Instagram login**. Use the
**Instagram App ID** and **Instagram App Secret** shown there, then set these in `.env`:

```dotenv
INSTAGRAM_APP_ID=YOUR_INSTAGRAM_APP_ID
INSTAGRAM_APP_SECRET=YOUR_INSTAGRAM_APP_SECRET
INSTAGRAM_REDIRECT_URI=https://kahoo.ir/api/instagram/callback
INSTAGRAM_TOKEN_ENCRYPTION_KEY=YOUR_FERNET_KEY
```

Generate the encryption key once with your Python environment:

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Keep the key outside version control and retain it across deployments; changing it
makes existing tokens unreadable. Tokens stay encrypted in PostgreSQL and never
go to browser storage or API responses.

Register the exact `INSTAGRAM_REDIRECT_URI` in the Instagram product's **Business
login settings**. Change this environment value when the public domain changes.
Serve the app at that same HTTPS origin so its session cookie survives the return
from Instagram. For local authorization tests, use a public HTTPS development URL
and register its callback too; `localhost` cannot receive a callback to `kahoo.ir`.

Rebuild to install dependencies and apply the connection migration:

```bash
docker compose --env-file .env.example --env-file .env up --build -d
```

During development, test with an Instagram account assigned an app/tester role.
For shops outside those roles, complete Meta's required App Review/Advanced Access
for `instagram_business_basic` and switch the app to Live mode. Follow Meta's
[Instagram Login documentation](https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/)
for app-dashboard requirements.

When a shop's profile is refreshed through `media sync`, Kahoo uses its stored
Instagram token and renews it when it has less than seven days remaining and is
over one day old. Expired/revoked tokens require the owner to connect again.
Authorization cancellation, failed imports and missing configuration show an error;
they never create a demo shop or claim a successful connection.

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
