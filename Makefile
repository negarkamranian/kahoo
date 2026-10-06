PYTHON = .venv/bin/python

.PHONY: check lint format format-check test run db-backup db-restore shop-enrich

BACKUP_DIR ?= backups

check: lint format-check test

lint:
	$(PYTHON) -m ruff check backend tests
	$(PYTHON) -m pylint backend
	npm run lint

format:
	$(PYTHON) -m ruff check --select I --fix backend tests
	$(PYTHON) -m ruff format backend tests
	npm run format

format-check:
	$(PYTHON) -m ruff format --check backend tests
	npm run format:check

test:
	$(PYTHON) -m unittest discover -s tests
	npm test
run:
	docker compose up -d app

db-backup:
	bash scripts/db-backup.sh --directory "$(BACKUP_DIR)"

db-restore:
	@test -n "$(RESTORE_DB)" || { echo 'Set RESTORE_DB to a new database name.' >&2; exit 2; }
	@test -n "$(BACKUP_FILE)" || { echo 'Set BACKUP_FILE to a backup archive.' >&2; exit 2; }
	bash scripts/db-restore.sh --database "$(RESTORE_DB)" "$(BACKUP_FILE)"

shop-enrich: db-backup
	docker compose --env-file .env.example --env-file .env up --build -d app
	docker compose --env-file .env.example --env-file .env run --rm app python3 -m backend search enrich-file data/merchant_enrichment.json
