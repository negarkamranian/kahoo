# Kahoo

Kahoo (کاهو) is a Persian RTL discovery app for Iranian Instagram shops.
Shoppers search stored profiles and posts, save items locally, and continue to Instagram.

## Start the app

```bash
cp .env.example .env
docker compose --env-file .env.example --env-file .env up --build
```

Open the [marketplace](http://127.0.0.1:4173), [saved items](http://127.0.0.1:4173/saved.html),
or [admin panel](http://127.0.0.1:4173/admin.html).

Startup applies PostgreSQL migrations and seeds categories. Merchant data stays
in the `kahoo-postgres` Docker volume. To populate a new database and fetch media:

```bash
docker compose --env-file .env.example --env-file .env run --rm app python3 -m backend catalog import
docker compose --env-file .env.example --env-file .env run --rm app python3 -m backend media sync --only-missing --limit 25
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
  models/              Typed contracts, grouped by domain
    common.py          Shared types and model base
    merchants.py       Merchant inputs, views, and import reports
    media.py           Normalized profiles, media, galleries, and sync reports
    categories.py      Category tree, GS1 publications, and generation policy
    catalog.py         Catalog snapshots and import reports
    analytics.py       Events and admin metrics
    auth.py            Login requests
    search.py          Search, enrichment, benchmarks, and command reports
    instagram/         Instagram wire schemas: common, embed, and Meta
  serialization.py     JSON serialization at HTTP and CLI output boundaries
  instagram/           Instagram profile adapters and embed parsing
  instagram_urls.py    Shared Instagram URL construction
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
Parse external JSON into Pydantic models in HTTP, CLI, and Instagram adapters.
Services pass those models using attributes and return structured models. Serialize
only at HTTP/CLI boundaries. Required fields fail validation; do not guess alternate
keys, identities, or content. Defaults belong in the owning model, and derived
values (such as post collection keys and cover images) have one definition.
Import contracts directly from their owning `backend.models` module; package
initializers do not re-export models.

Instagram wire contracts live in `backend/models/instagram/`. Embed posts require
`shortcode_media`, `__typename`, and `display_url`; Meta posts use `media_type`
to select image, video-thumbnail, or carousel fields. Media IDs are required.
An embed response must contain one media context with its profile and post list.
Migration 013 fills legacy collection keys once and requires them on future inserts.
Image downloads determine their MIME type from supported image signatures.

Search benchmarks use only `relevance` maps (grades 1–3); `expected_handles` is no
longer supported. Category generation validates GS1 publications and requires a
Persian label for every included category, from the translation publication plus
explicit policy overrides. Missing labels stop generation before writing output.
Analytics requests take the session ID only from `X-Kahoo-Session`.

## Common operations

Use `python3 -m backend` for every command. In Docker, prefix it with
`docker compose --env-file .env.example --env-file .env run --rm app`. Every command supports `--help`. Instagram handles
must already be in lowercase `@username` format.

| Command | Purpose |
| --- | --- |
| `serve [--host HOST] [--port PORT]` | Start the HTTP server. |
| `db migrate` | Apply schema migrations and seed categories. |
| `merchants list [--query TEXT]` | Inspect stored merchants. |
| `merchants add IDENTIFIER --category CODE` | Add or refresh an Instagram profile. |
| `merchants import-file PATH --category CODE` | Import @username handles from a text file. |
| `merchants remove ID` | Delete a merchant and exclude it from future catalog imports. |
| `catalog import [PATH ...]` | Import JSON snapshots; no paths means the checked-in catalogs. |
| `catalog build-categories --current PATH --persian PATH [--download]` | Rebuild the GS1 category seed using `data/gpc_policy.json`. |
| `media status [HANDLE ...]` | Report missing avatars and incomplete galleries. |
| `media sync [HANDLE ...] [--only-missing] [--limit N]` | Refresh profiles and galleries. |
| `media cache [HANDLE ...]` | Cache stored post URLs without refreshing profiles. |
| `search reindex [--batch-size N] [--all]` | Refresh metadata, search documents, and optional embeddings. |
| `search evaluate [--benchmark PATH]` | Run the reviewed relevance benchmark. |
| `search enrich ID PATH` | Import a sourced JSON description and search terms. |

Instagram imports use the fetched profile name and biography as the merchant name
and description. Manual name/description overrides are not supported. Missing or
blank profile names fail the import; an empty biography stays empty.

New merchants require an explicit GPC category; existing merchants retain theirs
when `--category` is omitted. Imports preserve snapshot provenance, newer live
metrics, and LLM descriptions. Use separate handle files for different categories.

For media sync, `--avatars-only` preserves galleries and `--limit 0` processes all
matches. Status and sync use `--minimum-post-images` (default: 3) for completeness.
Failed downloads preserve saved media. Commands report JSON on success. Runtime
errors stop the command with a traceback and a nonzero exit status; batches stop
at the first failure. Earlier completed profiles remain committed.

Unexpected HTTP request errors propagate to the server, which logs a traceback
and closes that request. Other requests continue running. Configured embedding
services must succeed; search does not silently fall back after an embedding error.

The former `python3 -m scripts` entry point is replaced by `python3 -m backend`.
The legacy SQLite importer has been removed; the app uses PostgreSQL.

## Configuration

All configuration defaults live in `.env.example`. Local runs load it automatically,
with `.env` and existing environment variables taking precedence. Docker Compose
loads both files through the `--env-file` arguments shown above. `backend/config.py` loads and validates the settings once at startup. Other modules
use its shared `settings` object; environment changes require a restart. Server CLI
flags override the configured host and port directly.

Missing profile pictures stay empty; no initials or generated avatars are used.

- `DATABASE_URL`: PostgreSQL connection for local runs; Compose supplies its own.
- `KAHOO_HOST` / `KAHOO_PORT`: server address; CLI flags override these.
- `KAHOO_ADMIN_TOKEN`: token required for admin mutations when configured.
  An empty token leaves mutations unlocked for development.
- `META_IG_USER_ID` / `META_ACCESS_TOKEN`: enable Meta Business Discovery.
  Without them, profile reads use the public Instagram embed reader.
- `EMBEDDING_API_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`: optional
  OpenAI-compatible embedding endpoint with 1024-dimensional vectors.

Search works without embeddings using stored content, Hazm normalization and stemming,
full-text search, and trigram matching. Enrichment JSON requires `description`,
`terms` (a list), `model`, and `source_url`; `confidence` is optional.
Search adds lowercase matching, ASCII digits, and punctuation/half-space separators
to Hazm's output. After upgrading from the handwritten normalizer, rebuild stored
search metadata and documents with `python3 -m backend search reindex`.
See [the search flow](docs/search-core-flow.md) for indexing and ranking details.

## Development and checks

Use Python 3.13 (also used by Docker) and Node.js 22.13+. Runtime dependencies
are in `requirements.txt`; development tools are in `requirements-dev.txt` and
`package.json` (with a checked-in npm lockfile).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
make check
pre-commit install
python -m backend --help
```

`make check` runs Ruff lint/import/complexity checks, Pylint, ESLint, Ruff and
Prettier formatting checks, and Python and JavaScript tests. `make format` applies
formatting and import sorting. `pre-commit run --all-files` also checks YAML/TOML,
trailing whitespace, and final newlines. CI runs the same checks on pushes and PRs.

Keep each function focused on one responsibility. Python complexity is limited to
8, Pylint allows at most 30 statements and 6 branches, and browser functions are
limited to 40 nonblank lines and complexity 8. Search scoring rules and explanation
priorities are named tables; adjust them in one place.

Tests and command help run without database or Instagram credentials.
Serving the app, database commands, and live search evaluation require PostgreSQL.
