PYTHON = .venv/bin/python

.PHONY: check lint format format-check test

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
