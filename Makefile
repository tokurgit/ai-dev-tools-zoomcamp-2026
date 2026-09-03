.DEFAULT_GOAL := help

# uv runs everything; no manual venv activation needed.
PY := uv run
MANAGE := $(PY) python manage.py

.PHONY: help install sync test test-file test-k coverage check run \
        shell migrate migrations superuser load-reference-data lint-migrations clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install sync: ## Install/sync dependencies (incl. dev group) from the lockfile
	uv sync

test: ## Run the full test suite
	$(PY) pytest

test-file: ## Run one test file/dir: make test-file F=auctions/tests/test_models.py
	$(PY) pytest $(F)

test-k: ## Run tests matching a name expression: make test-k K=test_source_id_is_unique
	$(PY) pytest -k "$(K)"

coverage: ## Run the suite with coverage (term-missing + HTML + coverage.xml)
	$(PY) pytest --cov-report=term-missing --cov-report=html --cov-report=xml

check: ## Run Django system checks
	$(MANAGE) check

run: ## Start the dev server (http://127.0.0.1:8000)
	$(MANAGE) runserver

shell: ## Open a Django shell
	$(MANAGE) shell

migrate: ## Apply database migrations
	$(MANAGE) migrate

migrations: ## Create new migrations from model changes
	$(MANAGE) makemigrations

superuser: ## Create an admin user
	$(MANAGE) createsuperuser

load-reference-data: ## Load Category/Region lookup tables from data/*.csv
	$(MANAGE) load_reference_data

lint-migrations: ## Fail if models have unmade migrations
	$(MANAGE) makemigrations --check --dry-run

clean: ## Remove the local SQLite db and Python bytecode caches
	rm -f db.sqlite3
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
