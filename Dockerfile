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

# Install Python dependencies + kokoro optional extra into /app/.venv.
# --extra kokoro installs: kokoro, soundfile, transformers>=4.47.0, click.
# transformers>=4.47.0 is required — older versions have a huggingface-hub<1.0
# runtime check that conflicts with huggingface-hub>=1.0 resolved by our other deps.
ENV VIRTUAL_ENV=/app/.venv
RUN uv sync --frozen --extra kokoro --no-install-project

# PyTorch (CPU) and WhisperX — not in pyproject.toml due to platform-specific wheels.
# uv pip install targets VIRTUAL_ENV directly; no pip binary exists in uv venvs.
RUN uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    uv pip install whisperx

# ── Production image ──────────────────────────────────────────────────────────
FROM base AS production

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy project source
COPY src/ src/
COPY pyproject.toml ./
# config/ contains brand_config.yaml and models-registry.yaml — both required at runtime
COPY config/ config/
COPY README.md ./
# Install the project itself (editable install in the existing venv)
RUN uv pip install -e . --no-deps

# Activate venv for all subsequent commands
ENV PATH="/app/.venv/bin:$PATH"
ENV VIRTUAL_ENV="/app/.venv"

# Runtime directories are mounted as volumes — create placeholders
RUN mkdir -p workspace/jobs workspace/music cache models logs assets temp

# Default working directory must match CWD requirement
WORKDIR /app

ENTRYPOINT ["ytfactory"]
CMD ["--help"]
