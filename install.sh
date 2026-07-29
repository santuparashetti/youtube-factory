#!/usr/bin/env bash
# YouTube Factory — one-command bootstrap for a fresh Linux (Ubuntu/Debian) machine.
#
# Usage (from a freshly cloned repo):
#   ./install.sh
#
# Idempotent — safe to re-run. Re-running skips steps that are already done
# and never overwrites an existing .env.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_root"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m⚠\033[0m %s\n' "$1"; }

if [[ ! -f pyproject.toml ]]; then
    echo "error: run this script from the youtube-factory repo root." >&2
    exit 1
fi

bold "YouTube Factory — Bootstrap"
echo

# ── Step 1: System dependencies (Debian/Ubuntu only) ─────────────────────────
if command -v apt-get >/dev/null 2>&1; then
    bold "Step 1/6 — System dependencies"
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        ffmpeg \
        git \
        curl \
        build-essential \
        libsndfile1 \
        espeak-ng \
        fonts-liberation \
        fonts-dejavu-core
    ok "System packages installed"
else
    warn "apt-get not found — this script targets Ubuntu/Debian."
    warn "On macOS/Windows, use the Docker path in docs/SETUP.md instead."
    warn "Continuing — make sure ffmpeg, espeak-ng, and build tools are on PATH."
fi
echo

# ── Step 2: uv (Python package manager) ───────────────────────────────────────
bold "Step 2/6 — uv"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
if command -v uv >/dev/null 2>&1; then
    ok "uv $(uv --version)"
else
    echo "error: uv install failed — install manually: https://docs.astral.sh/uv/" >&2
    exit 1
fi
echo

# ── Step 3: Python dependencies ───────────────────────────────────────────────
bold "Step 3/6 — Python dependencies (uv sync)"
uv sync
ok "Dependencies installed"
echo

# ── Step 4: .env ───────────────────────────────────────────────────────────────
bold "Step 4/6 — Environment file"
if [[ -f .env ]]; then
    ok ".env already exists — left untouched"
else
    cp .env.example .env
    warn ".env created from .env.example — you MUST edit it and add your API keys"
fi
echo

# ── Step 5: Workspace + BGM library layout ────────────────────────────────────
bold "Step 5/6 — Workspace directories"
mkdir -p workspace/music/{spiritual,meditation,cinematic_ambient,emotional_documentary,inspirational,calm_piano,nature_ambient}
mkdir -p cache models logs temp
ok "workspace/, cache/, models/, logs/, temp/ ready"
echo

# ── Step 6: Bootstrap engine (ML packages, provider checks, model manifest) ──
bold "Step 6/6 — ytfactory setup"
uv run ytfactory setup || warn "setup reported issues — see table above (often just missing API keys)"
echo

bold "Health check"
uv run ytfactory doctor || true
echo

bold "Done."
echo "Next steps:"
echo "  1. Edit .env and fill in your API keys (see docs/SETUP.md#provider-api-keys)."
echo "  2. Edit config/brand_config.yaml with your channel name/branding."
echo "  3. Drop a few royalty-free MP3s into workspace/music/<category>/ for BGM."
echo "  4. Re-run 'uv run ytfactory doctor' after adding keys, then try:"
echo "       uv run ytfactory run \"Your Topic\" --auto"
