# ============================================================
# Stage 1: Builder — install build tools and compile deps
# ============================================================
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    pkg-config \
    libssl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ============================================================
# Stage 2: Runtime — slim image, no build tools, non-root user
# ============================================================
FROM python:3.12-slim AS runtime

LABEL maintainer="MegaBot Team" \
      description="MegaBot AI orchestrator" \
      version="1.0.0"

# Runtime-only system deps (no compilers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgl1-mesa-glx \
    libglib2.0-0 \
    scrot \
    python3-tk \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get purge -y --auto-remove

# Create non-root user
RUN groupadd --gid 1000 megabot \
    && useradd --uid 1000 --gid megabot --shell /bin/bash --create-home megabot

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Create required directories owned by megabot
RUN mkdir -p /app/backups /app/media /app/data /app/logs \
    && chown -R megabot:megabot /app

# Copy application source (respect .dockerignore)
COPY --chown=megabot:megabot . .

# Ensure entrypoint is executable
RUN chmod +x /app/entrypoint.sh 2>/dev/null || true

# Environment configuration
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MEGABOT_MEDIA_PATH=/app/media

# Switch to non-root user
USER megabot

# Expose ports
EXPOSE 8000 18790

# Health check — hits the deep health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

# Use tini as PID 1 for proper signal handling
ENTRYPOINT ["tini", "--"]

# Default command — runs through entrypoint.sh for startup checks
# (DATABASE_URL validation, MEGABOT_AUTH_TOKEN check, memU installation)
CMD ["/app/entrypoint.sh"]
