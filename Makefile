# ─────────────────────────────────────────────────────────────────────
#  Coraxis — developer tasks
#  Run `make help` for the list.
# ─────────────────────────────────────────────────────────────────────

.DEFAULT_GOAL := help
PY      ?= python
VENV    ?= .venv
BIN     := $(VENV)/Scripts
ifeq ($(OS),)
	BIN := $(VENV)/bin
endif
PYTHON  := $(BIN)/python
PIP     := $(PYTHON) -m pip

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: venv
venv: ## Create the virtual environment
	$(PY) -m venv $(VENV)

.PHONY: install
install: ## Install runtime + dev dependencies (editable)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

.PHONY: install-postgres
install-postgres: ## Install the Postgres driver extra
	$(PIP) install -e ".[dev,postgres]"

.PHONY: migrate
migrate: ## Apply database migrations
	$(BIN)/alembic upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="add x"
	$(BIN)/alembic revision --autogenerate -m "$(m)"

.PHONY: downgrade
downgrade: ## Roll back one migration
	$(BIN)/alembic downgrade -1

.PHONY: serve
serve: ## Run the API with autoreload on :8000
	$(BIN)/uvicorn coraxis.main:app --reload --host 127.0.0.1 --port 8000

.PHONY: serve-prod
serve-prod: ## Run the API without autoreload
	$(BIN)/uvicorn coraxis.main:app --host 0.0.0.0 --port 8000

.PHONY: frontend
frontend: ## Run the Next.js dev server on :3000
	cd frontend && npm run dev

.PHONY: dev
dev: ## Run API and frontend together
	$(PYTHON) -m coraxis.cli.dev

.PHONY: lint
lint: ## Check style with ruff
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests

.PHONY: format
format: ## Auto-fix style with ruff
	$(BIN)/ruff check --fix src tests
	$(BIN)/ruff format src tests

.PHONY: typecheck
typecheck: ## Type-check with mypy (slow on a cold cache)
	$(BIN)/mypy src

.PHONY: test
test: ## Run the test suite
	$(BIN)/pytest

.PHONY: coverage
coverage: ## Run tests with a coverage report
	$(BIN)/pytest --cov=coraxis --cov-report=term-missing --cov-report=html

.PHONY: check
check: lint typecheck test ## Run every gate CI runs

.PHONY: clean
clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -prune -not -path "./$(VENV)/*" -exec rm -rf {} +
