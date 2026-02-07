#!/bin/bash
set -euo pipefail

echo "=== MegaBot Development Environment Setup ==="
echo ""

# ── Check prerequisites ─────────────────────────────────
check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo "ERROR: $1 is not installed. Please install it first." >&2
        return 1
    fi
    echo "  [OK] $1 found: $(command -v "$1")"
}

echo "Checking prerequisites..."
check_command python3
check_command pip
check_command node
check_command npm
echo ""

# ── Python dependencies ─────────────────────────────────
echo "Installing Python dependencies..."
pip install -r requirements.txt
pip install -r requirements-dev.txt
echo ""

# ── Frontend dependencies ───────────────────────────────
echo "Installing UI dependencies..."
(cd ui && npm ci)
echo ""

# ── Environment file ────────────────────────────────────
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "  [OK] .env created — edit it with your secrets before starting."
    else
        echo "  WARNING: No .env.example found. Create .env manually." >&2
    fi
else
    echo "  [OK] .env already exists."
fi
echo ""

# ── Verify setup ────────────────────────────────────────
echo "Running quick verification..."
python3 -c "import yaml, pydantic, fastapi; print('  [OK] Python imports OK')" 2>/dev/null || {
    echo "  WARNING: Some Python imports failed. Check requirements." >&2
}
(cd ui && npx tsc --noEmit 2>/dev/null && echo "  [OK] TypeScript compiles OK") || {
    echo "  WARNING: TypeScript compilation has errors." >&2
}
echo ""

# ── Summary ─────────────────────────────────────────────
echo "=== Setup Complete ==="
echo ""
echo "To start MegaBot:"
echo "  1. Edit .env with your API keys and secrets"
echo "  2. Start infrastructure:   docker compose up -d postgres redis ollama searxng"
echo "  3. Start orchestrator:     make run"
echo "  4. Start UI dev server:    cd ui && npm run dev"
echo ""
echo "Or run everything in Docker:"
echo "  docker compose up -d"
echo ""
