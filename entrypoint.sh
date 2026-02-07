#!/bin/bash
set -euo pipefail

# Trap signals for graceful shutdown
trap 'echo "Received shutdown signal, exiting..."; exit 0' SIGTERM SIGINT

echo "MegaBot Entrypoint Starting..."

# Verify critical environment
if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set" >&2
    exit 1
fi

if [ -z "${MEGABOT_AUTH_TOKEN:-}" ]; then
    echo "ERROR: MEGABOT_AUTH_TOKEN is not set" >&2
    exit 1
fi

# Ensure writable directories exist
for dir in /app/data /app/logs /app/media /app/backups; do
    if [ ! -d "$dir" ]; then
        echo "WARNING: Directory $dir does not exist, creating..." >&2
        mkdir -p "$dir" 2>/dev/null || echo "WARNING: Could not create $dir" >&2
    fi
done

# Check if memU is mounted and needs installation
if [ -d "/app/external_repos/memU" ] && [ -f "/app/external_repos/memU/pyproject.toml" ]; then
    echo "Found memU. Checking for installation..."
    if ! python -c "import memu" 2>/dev/null; then
        echo "Installing memU from source..."
        pip install --no-deps -e /app/external_repos/memU 2>&1 || {
            echo "WARNING: Failed to install memU, continuing without it" >&2
        }
    else
        echo "memU already installed."
    fi
else
    echo "WARNING: memU not found in /app/external_repos/memU. Using fallback mode." >&2
fi

echo "Starting MegaBot Orchestrator..."
exec python core/orchestrator.py
