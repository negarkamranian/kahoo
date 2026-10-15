# Kahoo

Persian RTL marketplace for Instagram shops. FastAPI, PostgreSQL/pgvector, and
vanilla JavaScript. Application data lives in PostgreSQL; `data/` holds import sources.

## Run

Set `KAHOO_ADMIN_TOKEN` in `.env` before using the admin panel.

```bash
cp .env.example .env
docker compose --env-file .env.example --env-file .env up --build -d
```

[Marketplace](http://localhost:4173) · [Admin](http://localhost:4173/admin.html) ·
[API docs](http://localhost:4173/docs)

Startup applies migrations automatically. Keep applied migration files unchanged.

## CLI

All operations use `python -m backend`. In Docker, prefix commands with
`docker compose exec app`. Use `--help` for available options.

```bash
python -m backend --help
python -m backend catalog import
python -m backend catalog sync-shopify --source data/shopify/2026-08/upstream-taxonomy.json.gz --license data/shopify/2026-08/LICENSE
python -m backend media sync --only-missing
python -m backend search reindex --all
```

To fetch missing post images in Docker, run `make media-sync` (or
`sudo make media-sync` if Docker requires sudo). This rebuilds the image before
syncing. `make shop-enrich` applies descriptions and search terms; it does not
download post images. Media sync reports failures per merchant and continues;
rerun it to retry missing media.

## Configuration

See [.env.example](.env.example). Set Instagram App ID, secret, redirect URI, and
`INSTAGRAM_TOKEN_ENCRYPTION_KEY` to enable store connections. Generate the key with
`python -m backend instagram generate-key`; keep it stable. Register the exact
redirect URI in Meta; the default is `https://kahoo.ir/api/instagram/callback`.

Search combines lexical and vector results when `EMBEDDING_API_URL` is configured.
For product extraction, import the Shopify taxonomy, configure `PRODUCT_VISION_*`,
and start `docker compose --profile enrichment up -d product-worker`.

Phone login currently uses an unverified demo flow without SMS delivery.

## Development

Python 3.13 and Node.js 22.13+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci
make check
```

Set `KAHOO_TEST_DATABASE_URL` to run PostgreSQL integration tests.
