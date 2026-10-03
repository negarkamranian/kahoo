# Kahoo

Kahoo (کاهو) is a Persian RTL discovery layer for Iranian Instagram shops.
Shoppers search stored merchant profiles and posts, save items locally, and
continue to Instagram.

## Run

```bash
cp .env.example .env
docker compose up --build
```

- Marketplace: `http://127.0.0.1:4173`
- Saved items: `http://127.0.0.1:4173/saved.html`
- Admin: `http://127.0.0.1:4173/admin.html`

PostgreSQL with pgvector stores runtime data in the `kahoo-postgres` Docker
volume. Startup applies SQL migrations and the GS1 category seed. It does not
import merchant snapshots, overwrite merchant profiles, or contact Instagram.
For a new database, import the reviewed catalogs explicitly:

```bash
docker compose run --rm app python3 -m scripts catalog import
docker compose run --rm app python3 -m scripts media sync --only-missing --limit 25
```

Existing merchant records remain available without reimporting. The old
`KAHOO_SEED_DEMO` and `KAHOO_SYNC_ON_START` settings have been removed.

## CLI

All maintained operations use `python3 -m scripts`. Each command has `--help`.
Inside Docker, prefix commands with `docker compose run --rm app`.

| Command | Purpose |
| --- | --- |
| `serve [--host HOST] [--port PORT]` | Start the HTTP server; defaults also read `KAHOO_HOST` and `KAHOO_PORT`. |
| `db migrate` | Apply schema migrations and seed categories. |
| `db import-sqlite --source PATH [--database-url URL]` | Import a legacy SQLite database. |
| `merchants list [--query TEXT] [--limit N] [--offset N]` | Inspect stored merchants. |
| `merchants add IDENTIFIER [--category CODE]` | Add or refresh a public Instagram profile. |
| `merchants remove ID` | Delete a merchant and record a persistent catalog exclusion. |
| `merchants import-file PATH [--category CODE]` | Import whitespace-separated handles or Instagram profile URLs. |
| `catalog import [PATH ...]` | Import supplied JSON catalogs; no paths means the checked-in snapshots. |
| `catalog build-categories --current PATH --persian PATH [--download]` | Rebuild the GS1 category seed using `data/gpc_policy.json`. |
| `media status [HANDLE ...]` | Report missing/generated avatars and incomplete/outdated galleries. |
| `media sync [HANDLE ...]` | Refresh profiles, avatars, and post galleries. |
| `media cache [HANDLE ...]` | Download uncached post URLs already stored in the database. |
| `search reindex [--batch-size N] [--all]` | Refresh metadata, documents, and optional embeddings. |
| `search evaluate [--benchmark PATH]` | Measure relevance against reviewed benchmark judgments. |
| `search enrich ID PATH` | Apply a JSON description and search terms with source/model provenance. |

JSON reports are written to stdout. Failures return a nonzero exit status,
including partial failures in batch profile imports and media synchronization.

### Merchant imports

New merchants require an explicit GPC category. Existing merchants retain their
assigned category when `--category` is omitted. The admin selector reads the
same database category tree; there are no keyword-to-category rules or default
assignments to clothing. Optional `--name`, `--description`, and `--city` values
override profile defaults. Use separate input files when importing new merchants
into different categories.

```bash
python3 -m scripts merchants add @shop_username --category 66010100
python3 -m scripts merchants import-file phone-shops.txt --category 66010100
python3 -m scripts merchants list --query shop_username
```

Catalog imports preserve source URLs and each shard's snapshot timestamp. They
respect persistent exclusions, preserve LLM descriptions and newer live metrics,
and store additional categories as database assignments. The initial seed is
ordinary snapshot data in `data/merchant_seed.json`; it contains no synthetic
gallery entries. Imports and media synchronization refresh search documents.

### Instagram media

Set `META_IG_USER_ID` and `META_ACCESS_TOKEN` in `.env` to use Meta Business
Discovery. Without credentials, the existing public-embed reader can read
available public profiles. Profile availability and downloadable media depend
on Instagram. Failed downloads preserve existing saved media.

```bash
python3 -m scripts media status
python3 -m scripts media sync --only-missing --limit 25
python3 -m scripts media sync @shop_username --avatars-only
python3 -m scripts media sync --avatars-only --only-missing --limit 25
python3 -m scripts media cache @shop_username
```

`--minimum-post-images N` controls gallery completeness for status and sync;
it defaults to 3. `--limit 0` means all matching profiles. `--avatars-only`
updates profile pictures without replacing galleries. `media cache` operates
only on the requested handles when provided.

The former profile, avatar, gallery-backfill, and missing-media scripts are
replaced by these commands. The one-off expansion and shared-list builders
were removed; checked-in catalogs remain importable, and new handle lists use
`merchants import-file` with an explicit category.

### Search

Search indexes merchant names, handles, descriptions, biographies, assigned
category labels, sourced enrichment, and post captions. Persian normalization,
morphology, weighted full-text search, and trigram matching handle lexical
retrieval. Optional embeddings provide semantic matches; ranking combines the
retrievers with coverage, proximity, and bounded behavioral signals.

There is no seeded synonym dictionary or alias-expansion stage. Suggestions
come from stored merchants, category labels, extracted terms, and successful
search history. A new product term becomes searchable through import or reindex,
without changing application code. Without embeddings, unrelated spellings or
synonyms need evidence in the indexed content to match. Normalization rules and
ranking parameters remain algorithmic constants, not lists of products or shops.

Migration `011_remove_search_aliases.sql` removes the unused legacy alias table.
To rebuild the index after updating:

```bash
python3 -m scripts search reindex --all
python3 -m scripts search evaluate
```

For semantic retrieval, configure an OpenAI-compatible embedding endpoint with
1024-dimensional vectors using `EMBEDDING_API_URL`, `EMBEDDING_API_KEY`, and
`EMBEDDING_MODEL`. Embedding batches commit individually. Enrichment JSON needs
`description`, `terms` (a list), `model`, and `source_url`; `confidence` is optional.
See [the search flow](docs/search-core-flow.md).

### Admin and legacy data

Set `KAHOO_ADMIN_TOKEN` in `.env` and enter it in the admin panel to protect
merchant mutations. An empty token leaves mutations unlocked for development.
The login and OAuth-shaped onboarding screens remain prototypes.

To import the previous SQLite data before serving:

```bash
docker compose up -d db
docker compose build app
docker compose run --rm \
  -v ./data/kahoo.db:/legacy/kahoo.db:ro \
  app python3 -m scripts db import-sqlite --source /legacy/kahoo.db
```

## Structure

```text
backend/
  database.py          PostgreSQL connections and migrations
  catalog.py           Snapshot parsing and validation
  instagram.py         Instagram identity parsing and profile readers
  server/
    app.py             HTTP server lifecycle
    http.py            Routing, validation, authentication and responses
    analytics.py       Event recording and metrics
    categories.py      Database category tree
    merchants.py       Merchant reads, gallery presentation and removal
    media.py           Image downloads and persistence
    profiles.py        Profile/media synchronization and completeness
  search/
    normalization.py   Persian normalization and tokenization
    metadata.py        Metadata derived from stored merchant records
    indexing.py        Merchant and post documents
    retrieval.py       PostgreSQL lexical retrieval
    embeddings.py      Embedding API and vector retrieval
    ranking.py         Matching, relevance and diversity functions
    service.py         Search orchestration and result assembly
    suggestions.py     Database-backed autocomplete
scripts/
  cli.py               CLI commands and validation
  merchants.py         Shared CLI/admin import workflow
  catalog.py           Explicit snapshot imports
  categories.py        GS1 publication processing
  media.py             Media maintenance actions
  search.py            Indexing and evaluation actions
  enrichment.py        Sourced enrichment import
  database.py          Database setup and legacy import
public/                Marketplace, saved-items and admin UI
data/                  Reviewed catalogs, taxonomy policy and relevance judgments
db/migrations/         Versioned PostgreSQL schema
```

## Checks

Use Python 3.13 or newer and Node.js 22 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt ruff
.venv/bin/python -m unittest discover -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
node --test tests/*.test.mjs
.venv/bin/python -m scripts --help
```

Unit tests and command help do not need database or Instagram credentials.
Live search evaluation and database operations require PostgreSQL.
