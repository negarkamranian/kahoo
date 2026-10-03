# Kahoo

Kahoo (کاهو) is a Persian RTL discovery app for Iranian Instagram shops.
Shoppers search stored profiles and posts, save items locally, and continue to Instagram.

## Start the app

```bash
cp .env.example .env
docker compose up --build
```

Open the [marketplace](http://127.0.0.1:4173), [saved items](http://127.0.0.1:4173/saved.html),
or [admin panel](http://127.0.0.1:4173/admin.html).

Startup applies PostgreSQL migrations and seeds categories. Merchant data stays
in the `kahoo-postgres` Docker volume. To populate a new database and fetch media:

```bash
docker compose run --rm app python3 -m backend catalog import
docker compose run --rm app python3 -m backend media sync --only-missing --limit 25
```

Catalog import is explicit; normal startup does not import snapshots or contact Instagram.

## Project structure

```text
backend/
  __main__.py          Entry point: python -m backend
  cli/                 Command-line interface
    __init__.py        Command parsing, validation, and dispatch
    catalog.py         Catalog import and category seed generation
    merchants.py       Merchant management commands
    media.py           Media maintenance commands
    search.py          Search indexing, evaluation, and enrichment commands
  server/              HTTP server lifecycle and request handling
  services/            Shared application logic
    catalog.py         Snapshot validation and import
    merchants.py       Merchant reads, imports, and removal
    profiles.py        Profile synchronization and media completeness
    media.py           Image downloads, caching, and persistence
    categories.py      Category tree
    analytics.py       Events and admin metrics
  search/              Normalization, indexing, retrieval, ranking, enrichment
  database.py          PostgreSQL connections and shared database setup
  instagram.py         Instagram identifiers and profile readers
public/                HTML pages and browser CSS/JavaScript
  assets/css/
  assets/js/
data/                  Reviewed merchant catalogs, category seed, search benchmarks
db/migrations/         Ordered, versioned PostgreSQL schema changes
tests/                 Python tests and browser-module tests
docs/                  Search details, product research, and source notes
  archive/             Historical planning notes
```

The request flow is **browser → HTTP handler → services/search → PostgreSQL**.
CLI commands call the same services. Both server startup and database-backed
commands use `database.initialize_database()` for schema and category setup.
Merchant imports and profile updates refresh search metadata and documents.

Start with `backend/server/http.py` for routes, `backend/cli/__init__.py` for commands,
and `backend/search/service.py` for search orchestration. Shared application
logic belongs in `services/`; request and command handling stays at the edges.

## Common operations

Use `python3 -m backend` for every command. In Docker, prefix it with
`docker compose run --rm app`. Every command supports `--help`.

| Command | Purpose |
| --- | --- |
| `serve [--host HOST] [--port PORT]` | Start the HTTP server. |
| `db migrate` | Apply schema migrations and seed categories. |
| `merchants list [--query TEXT]` | Inspect stored merchants. |
| `merchants add IDENTIFIER --category CODE` | Add or refresh an Instagram profile. |
| `merchants import-file PATH --category CODE` | Import handles or profile URLs from a text file. |
| `merchants remove ID` | Delete a merchant and exclude it from future catalog imports. |
| `catalog import [PATH ...]` | Import JSON snapshots; no paths means the checked-in catalogs. |
| `catalog build-categories --current PATH --persian PATH [--download]` | Rebuild the GS1 category seed using `data/gpc_policy.json`. |
| `media status [HANDLE ...]` | Report missing avatars and incomplete galleries. |
| `media sync [HANDLE ...] [--only-missing] [--limit N]` | Refresh profiles and galleries. |
| `media cache [HANDLE ...]` | Cache stored post URLs without refreshing profiles. |
| `search reindex [--batch-size N] [--all]` | Refresh metadata, search documents, and optional embeddings. |
| `search evaluate [--benchmark PATH]` | Run the reviewed relevance benchmark. |
| `search enrich ID PATH` | Import a sourced JSON description and search terms. |

New merchants require an explicit GPC category; existing merchants retain theirs
when `--category` is omitted. Imports preserve snapshot provenance, newer live
metrics, and LLM descriptions. Use separate handle files for different categories.

For media sync, `--avatars-only` preserves galleries and `--limit 0` processes all
matches. Status and sync use `--minimum-post-images` (default: 3) for completeness.
Failed downloads preserve saved media. Commands report JSON and return a nonzero
status on failure, including partial batch failures.

The former `python3 -m scripts` entry point is replaced by `python3 -m backend`.
The legacy SQLite importer has been removed; the app uses PostgreSQL.

## Configuration

Docker Compose reads `.env`; local runs need variables exported in the shell.
See `.env.example` for available settings.

- `DATABASE_URL`: PostgreSQL connection for local runs; Compose supplies its own.
- `KAHOO_HOST` / `KAHOO_PORT`: server address; CLI flags override these.
- `KAHOO_ADMIN_TOKEN`: token required for admin mutations when configured.
  An empty token leaves mutations unlocked for development.
- `META_IG_USER_ID` / `META_ACCESS_TOKEN`: enable Meta Business Discovery.
  Without them, profile reads use the public Instagram embed reader.
- `EMBEDDING_API_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`: optional
  OpenAI-compatible embedding endpoint with 1024-dimensional vectors.

Search works without embeddings using stored content, Persian normalization,
full-text search, and trigram matching. Enrichment JSON requires `description`,
`terms` (a list), `model`, and `source_url`; `confidence` is optional.
See [the search flow](docs/search-core-flow.md) for indexing and ranking details.

## Development and checks

Use Python 3.13+ and Node.js 22+. Python dependencies are defined in
`requirements.txt`; `pyproject.toml` configures Ruff.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt ruff
.venv/bin/python -m unittest discover -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
node --test tests/*.test.mjs
.venv/bin/python -m backend --help
```

Tests and command help run without database or Instagram credentials.
Serving the app, database commands, and live search evaluation require PostgreSQL.
