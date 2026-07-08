# YouTube Factory — Production Dockerfile
# ─────────────────────────────────────────────────────────────────────────────
# Baked in:  Python, uv, project source, Python dependencies, FFmpeg, Git
# NOT baked: workspace, models, cache, logs, API keys
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    build-essential \
    libsndfile1 \
    espeak-ng \
    fonts-liberation \
    fonts-dejavu-core \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ── Builder stage — install dependencies ─────────────────────────────────────
FROM base AS builder

# Copy dependency files first (layer cache — only rebuilds if deps change)
COPY pyproject.toml uv.lock* ./

# Install Python dependencies into /app/.venv
RUN uv sync --frozen --no-install-project

# ── Production image ──────────────────────────────────────────────────────────
FROM base AS production

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy project source
COPY src/ src/
COPY pyproject.toml ./
COPY brand_config.yaml* ./

# Install the project itself (editable install in the existing venv)
RUN /app/.venv/bin/pip install -e . --no-deps --quiet

# Activate venv for all subsequent commands
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Runtime directories are mounted as volumes — create placeholders
RUN mkdir -p workspace/jobs workspace/music cache models logs assets temp

# Default working directory must match CWD requirement
WORKDIR /app

ENTRYPOINT ["ytfactory"]
CMD ["--help"]
