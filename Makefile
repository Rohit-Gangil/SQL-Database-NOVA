.PHONY: help setup lint test test-fast simulate warehouse features backtest policy results site all clean db-up db-down db-init

PY := python

help:
	@echo "NOVA - pharmacy replenishment decision system"
	@echo ""
	@echo "  make setup      install pinned dependencies"
	@echo "  make all        full pipeline: simulate -> warehouse -> features -> backtest -> policy"
	@echo ""
	@echo "  make simulate   generate the synthetic dataset (~90s, 5.9M rows)"
	@echo "  make warehouse  build analytics marts + run data-quality checks"
	@echo "  make features   build the point-in-time feature table"
	@echo "  make backtest   rolling-origin backtest of the model ladder"
	@echo "  make policy     head-to-head policy cost comparison"
	@echo ""
	@echo "  make test       full test suite"
	@echo "  make test-fast  skip tests needing the generated dataset"
	@echo "  make lint       ruff"
	@echo ""
	@echo "  make db-up      start PostgreSQL (Layer 0) via docker compose"
	@echo "  make db-init    apply DDL, functions, indexes, policies"
	@echo "  make db-down    stop PostgreSQL"

setup:
	$(PY) -m pip install -e ".[dev]"

# --- Pipeline --------------------------------------------------------
simulate:
	$(PY) -m nova.simulator.run

warehouse:
	$(PY) -m nova.warehouse.build --strict

features:
	$(PY) -c "import duckdb; from nova.config import DUCKDB_PATH; from nova.features.build import build_features; \
	          con=duckdb.connect(str(DUCKDB_PATH)); print(f'{build_features(con):,} rows'); con.close()"

backtest:
	$(PY) -m nova.forecast.backtest

policy:
	$(PY) -m nova.inventory.compare

results:
	$(PY) -m nova.report.results

site:
	$(PY) -m nova.report.build_site

all: simulate warehouse features backtest policy results site

# --- Quality ---------------------------------------------------------
lint:
	ruff check nova tests

test:
	$(PY) -m pytest

test-fast:
	$(PY) -m pytest -m "not slow"

# --- Layer 0 (PostgreSQL) --------------------------------------------
# NOTE: unverified -- no Docker on the machine this was built on (D-005).
db-up:
	docker compose up -d
	docker compose exec -T postgres sh -c 'until pg_isready -U nova; do sleep 1; done'

db-init:
	docker compose exec -T postgres psql -U nova -d nova -v ON_ERROR_STOP=1 -f /docker-entrypoint-initdb.d/01-ddl/00_schema.sql

db-down:
	docker compose down

clean:
	rm -rf data/*.duckdb artifacts/* .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
