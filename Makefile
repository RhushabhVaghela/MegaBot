.PHONY: install install-dev test test-cov lint format typecheck security audit clean build \
       docker-build docker-up docker-down docker-logs run setup help

# ── Default target ──────────────────────────────────────
help:
	@echo "MegaBot Development Commands"
	@echo "──────────────────────────────────────────"
	@echo "  make install       Install production deps"
	@echo "  make install-dev   Install dev + production deps"
	@echo "  make setup         Full development environment setup"
	@echo ""
	@echo "  make test          Run tests"
	@echo "  make test-cov      Run tests with coverage (95% threshold)"
	@echo "  make lint          Lint with ruff"
	@echo "  make format        Auto-format with ruff"
	@echo "  make typecheck     Run mypy type checking"
	@echo "  make security      Run bandit security scan"
	@echo "  make audit         Run pip-audit dependency scan"
	@echo "  make ci            Run full CI pipeline locally"
	@echo ""
	@echo "  make run           Start MegaBot orchestrator"
	@echo "  make build         Build Python package"
	@echo "  make clean         Remove caches and build artifacts"
	@echo ""
	@echo "  make docker-build  Build Docker image"
	@echo "  make docker-up     Start all services"
	@echo "  make docker-down   Stop all services"
	@echo "  make docker-logs   Tail service logs"
	@echo ""

# ── Installation ────────────────────────────────────────
install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements.txt -r requirements-dev.txt

setup:
	bash setup.sh

# ── Testing ─────────────────────────────────────────────
test:
	PYTHONPATH=. OPENCLAW_AUTH_TOKEN=test_token_12345 python3 -m pytest tests/ -v

test-cov:
	PYTHONPATH=. OPENCLAW_AUTH_TOKEN=test_token_12345 python3 -m pytest tests/ \
		--cov=megabot \
		--cov-report=term-missing --cov-report=html \
		--cov-fail-under=95

# ── Linting & Type-checking ────────────────────────────
lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy --ignore-missing-imports .

# ── Security ────────────────────────────────────────────
security:
	bandit -r megabot/ -c pyproject.toml --severity-level medium

audit:
	pip-audit --strict --desc

# ── Full CI locally ─────────────────────────────────────
ci: lint typecheck test-cov security audit
	@echo ""
	@echo "All CI checks passed."

# ── Run ─────────────────────────────────────────────────
run:
	PYTHONPATH=. python3 -m megabot.core.orchestrator

# ── Build ───────────────────────────────────────────────
build:
	python -m build

# ── Docker ──────────────────────────────────────────────
docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f --tail=100

# ── Cleanup ─────────────────────────────────────────────
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage coverage.xml .mypy_cache .ruff_cache dist build *.egg-info
