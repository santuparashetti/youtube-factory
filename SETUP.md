# YouTube Factory — Installation Guide

Complete step-by-step guide to replicate the current production environment on a new machine.

---

## System Requirements

| Component | Minimum | Current system |
|---|---|---|
| OS | Ubuntu 20.04+ / Debian 11+ | Ubuntu 22.04 |
| Python | 3.10+ | 3.10.12 |
| RAM | 8 GB | 8 GB |
| Storage | 10 GB free | — |
| GPU | Optional | CPU-only |

> **Windows / macOS:** Use the [Docker path](#option-b-docker-recommended-for-any-os) instead.

---

## Option A — Native (Linux / Ubuntu)

### Step 1 — System Dependencies

```bash
sudo apt update && sudo apt install -y \
    python3 python3-pip python3-venv \
    ffmpeg \
    git \
    curl \
    build-essential \
    libsndfile1 \
    espeak-ng \
    fonts-liberation \
    fonts-dejavu-core
```

Verify:
```bash
python3 --version     # must be 3.10+
ffmpeg -version       # must succeed
espeak-ng --version   # required for Kokoro TTS
```

---

### Step 2 — Install uv

`uv` is the Python package manager used by this project (replaces pip + venv).

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env   # or open a new terminal
uv --version
```

---

### Step 3 — Clone and Enter the Repository

```bash
git clone <your-repo-url> youtube-factory
cd youtube-factory
```

All commands from this point forward must be run from the `youtube-factory/` root.
The `.env` file and `workspace/` are resolved relative to the current directory — never `cd` into subdirectories.

---

### Step 4 — Install Python Dependencies

```bash
uv sync
```

This creates `.venv/` and installs all packages from `pyproject.toml`.

---

### Step 5 — Install AI / ML Packages (Manual)

These are not in `pyproject.toml` because they have heavy/platform-specific wheels. Install once after `uv sync`.

#### Kokoro TTS (local neural text-to-speech)

```bash
uv pip install kokoro soundfile
```

- First run downloads ~300 MB of model weights automatically.
- No API key needed.

#### WhisperX (forced alignment for subtitle timing)

```bash
uv pip install whisperx
```

- Downloads wav2vec2 alignment model on first use (~100 MB).
- Required only when `WHISPERX_ENABLED=true`.

#### PyTorch (CPU version — skip if you have CUDA)

If the above installs failed with a torch error, install CPU torch first:

```bash
uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
uv pip install kokoro soundfile whisperx
```

#### PyTorch (CUDA — for GPU acceleration)

```bash
# CUDA 12.x
uv pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
uv pip install kokoro soundfile whisperx
```

---

### Step 6 — Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in your API keys:

```bash
# Required — pick one LLM provider
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=https://api.anthropic.com   # or your LiteLLM proxy URL
ANTHROPIC_MODEL=claude-haiku-4-5

# Required — web search
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-...

# Required — image generation
IMAGE_PROVIDER=huggingface
HF_TOKEN=hf_...
HF_IMAGE_MODEL=black-forest-labs/FLUX.1-schnell

# TTS provider (kokoro = local, no API key needed)
TTS_PROVIDER=kokoro
KOKORO_SPEED=0.85

# WhisperX (word-level subtitle alignment)
WHISPERX_ENABLED=true
WHISPERX_DEVICE=cpu      # or cuda

# Video output
IMAGE_WIDTH=1280
IMAGE_HEIGHT=720
RENDER_PROFILE=balanced

# BGM (background music)
BGM_ENABLED=true
BGM_CATEGORY=auto
BGM_LIBRARY_PATH=workspace/music
BGM_VOLUME=0.24
BGM_DUCK_THRESHOLD=0.02
BGM_DUCK_RATIO=6.2
BGM_FADE_IN_SECONDS=3.0
BGM_FADE_OUT_SECONDS=4.0

# Pacing (contemplative pauses for spiritual content)
TTS_PACING_PROFILE=spiritual
```

> **Other LLM providers:**
> - `LLM_PROVIDER=gemini` → `GEMINI_API_KEY=...`
> - `LLM_PROVIDER=groq` → `GROQ_API_KEY=...`

---

### Step 7 — Bootstrap the Environment

```bash
uv run ytfactory setup
```

This will:
- Verify Python, FFmpeg, Git, Torch, fonts
- Create all required directories (`workspace/`, `cache/`, `models/`, `logs/`, `temp/`)
- Validate your API keys
- Check provider connectivity
- Write `bootstrap-manifest.json` and `environment-report.json`

Expected output: `✓ Setup complete — environment ready`

If you see errors, fix the specific issue shown then re-run `ytfactory setup`.

---

### Step 8 — Run Doctor (Health Check)

```bash
uv run ytfactory doctor
```

All checks should show `✓`. Common warnings that are OK:
- `env:torch (CPU only)` — normal on machines without CUDA
- `provider:edge-tts connectivity check failed` — Edge TTS only needs connectivity when generating audio

---

### Step 9 — Music Library Setup

The BGM engine reads from `workspace/music/`. Create one subdirectory per mood category and drop MP3 files in:

```
workspace/music/
├── spiritual/          ← used when BGM_CATEGORY=spiritual or auto-detected
├── meditation/
├── cinematic_ambient/
├── emotional_documentary/
├── inspirational/
├── calm_piano/
└── nature_ambient/
```

```bash
mkdir -p workspace/music/{spiritual,meditation,cinematic_ambient,emotional_documentary,inspirational,calm_piano,nature_ambient}
# Then copy your MP3 files into the appropriate subdirectories
```

Recommended: royalty-free tracks from [Free Music Archive](https://freemusicarchive.org/) or [YouTube Audio Library](https://studio.youtube.com/channel/audiomono/music).

When `BGM_CATEGORY=auto`, the pipeline selects the category based on the video topic. When `BGM_ENABLED=true` but the music folder is empty, BGM is silently skipped.

---

### Step 10 — Brand Configuration

Edit `config/brand_config.yaml` to match your channel:

```yaml
channel_name: "Your Channel Name"

opening:
  enabled: true
  template: |
    Welcome to [Your Channel]...
    where [your tagline].

closing:
  enabled: true
  template: |
    This is [Your Channel].

cta:
  enabled: true
  template: |
    If this resonated with you,
    consider joining us on this journey.

signature:
  enabled: true
  template: |
    Your closing tagline.
    Second line.

voice:
  pace: calm
  pause_after_opening_ms: 800
  pause_after_closing_ms: 1000

branding:
  opening_position: after_hook
  closing_position: before_final_quote
  max_opening_seconds: 10
  asset_path: "assets/branding/your-brand.png"
  asset_animation: "slow_zoom"
```

Place your brand card image at `assets/branding/your-brand.png`:
- Size: 1280×720 (or 1920×1080 for Full HD)
- Format: PNG (transparency supported)
- This image appears as a scene during the closing narration

---

### Step 11 — Verify with a Test Build

```bash
# Create a project
uv run ytfactory create "Test Video"
# Note the project ID printed (e.g. test-video)

# Import a short test script
uv run ytfactory import-script test-video samples/scripts/script.txt

# Run the full pipeline
uv run ytfactory build test-video
```

Or run the full agentic pipeline with a topic:
```bash
uv run ytfactory run "The Power of Stillness" --auto
```

---

## Option B — Docker (Recommended for Any OS)

### Prerequisites

- Docker Engine 24+ or Docker Desktop
- 10 GB free disk space

### Step 1 — Clone

```bash
git clone <your-repo-url> youtube-factory
cd youtube-factory
```

### Step 2 — Configure API Keys

```bash
cp .env.example .env
# Edit .env and fill in your API keys (same as Step 6 above)
```

### Step 3 — Start the Container

```bash
docker compose up -d
```

The image is built on first run (~5–10 min). Subsequent starts are instant.

### Step 4 — Bootstrap Inside the Container

```bash
docker exec youtube-factory ytfactory setup
docker exec youtube-factory ytfactory doctor
```

### Step 5 — Music Library

Mount your music library or copy files:
```bash
# Copy local music into the container's volume
docker cp workspace/music/. youtube-factory:/app/workspace/music/
```

Or add a bind mount in `docker-compose.yml`:
```yaml
volumes:
  - ./workspace/music:/app/workspace/music:ro
```

### Step 6 — Build a Video

```bash
docker exec youtube-factory ytfactory run "Your Topic" --auto
```

### GPU Support

```bash
docker compose --profile gpu up -d
docker exec youtube-factory ytfactory doctor
```

Requires NVIDIA drivers and `nvidia-container-toolkit` installed on the host.

---

## Provider API Keys — Where to Get Them

| Key | Provider | URL | Notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic | console.anthropic.com | Powers LLM (script, research, publish) |
| `ANTHROPIC_BASE_URL` | LiteLLM proxy | your proxy URL | Set to `https://api.anthropic.com` for direct |
| `TAVILY_API_KEY` | Tavily | app.tavily.com | Web search for research stage |
| `HF_TOKEN` | HuggingFace | huggingface.co/settings/tokens | Image generation (FLUX.1) |
| `GEMINI_API_KEY` | Google | aistudio.google.com | Alternative LLM or image provider |
| `GROQ_API_KEY` | Groq | console.groq.com | Fast/cheap alternative LLM |

---

## Complete `.env` Reference

```bash
# ── LLM ─────────────────────────────────────────────────────────────────────
LLM_PROVIDER=anthropic          # gemini | anthropic | groq | ollama
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=claude-haiku-4-5
GEMINI_API_KEY=                 # if LLM_PROVIDER=gemini
GEMINI_TEXT_MODEL=gemini-2.5-flash
GROQ_API_KEY=                   # if LLM_PROVIDER=groq
GROQ_MODEL=llama-3.1-8b-instant

# ── Search ───────────────────────────────────────────────────────────────────
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=tvly-...

# ── Image Generation ─────────────────────────────────────────────────────────
IMAGE_PROVIDER=huggingface      # huggingface | gemini | pollinations
HF_TOKEN=hf_...
HF_IMAGE_MODEL=black-forest-labs/FLUX.1-schnell
GEMINI_IMAGE_MODEL=gemini-3.1-flash-lite-image
IMAGE_WIDTH=1280
IMAGE_HEIGHT=720

# ── TTS ─────────────────────────────────────────────────────────────────────
TTS_PROVIDER=kokoro             # kokoro | edge | elevenlabs
KOKORO_VOICE=am_michael         # am_michael | am_adam | af_sarah
KOKORO_SPEED=0.85               # 1.0 = natural, 0.85 = contemplative

# ── WhisperX ─────────────────────────────────────────────────────────────────
WHISPERX_ENABLED=true
WHISPERX_DEVICE=cpu             # cpu | cuda

# ── Video & Rendering ────────────────────────────────────────────────────────
RENDER_PROFILE=balanced         # draft | balanced | cinematic | premium
REQUEST_TIMEOUT=60

# ── Background Music ─────────────────────────────────────────────────────────
BGM_ENABLED=true
BGM_CATEGORY=auto               # auto | spiritual | meditation | cinematic_ambient | ...
BGM_LIBRARY_PATH=workspace/music
BGM_VOLUME=0.24
BGM_DUCK_THRESHOLD=0.02
BGM_DUCK_RATIO=6.2
BGM_FADE_IN_SECONDS=3.0
BGM_FADE_OUT_SECONDS=4.0

# ── Pacing ───────────────────────────────────────────────────────────────────
TTS_PACING_PROFILE=spiritual    # normal | documentary | spiritual | meditation

# ── Image Review (Vision Quality Gate — optional, requires ~10 GB disk) ──────
IMAGE_REVIEW_ENABLED=false
VISION_REVIEW_PROVIDER=local
VISION_REVIEW_LOCAL_MODEL=minicpm_v2_6
IMAGE_REVIEW_MIN_SCORE=90
IMAGE_REVIEW_CONFIDENCE=80
IMAGE_REVIEW_MAX_ATTEMPTS=3
IMAGE_REVIEW_AUTO_REMEDIATE=true
```

---

## Directory Structure After Setup

```
youtube-factory/
├── .env                        ← your API keys (gitignored)
├── config/
│   ├── brand_config.yaml       ← channel branding (canonical location)
│   └── models-registry.yaml    ← LAMM model registry
├── src/ytfactory/              ← source code
├── workspace/
│   ├── jobs/                   ← project outputs (gitignored)
│   └── music/                  ← BGM library
│       ├── spiritual/
│       ├── meditation/
│       └── ...
├── assets/
│   └── branding/
│       └── your-brand.png      ← channel brand card
├── base_scripts/               ← reference scripts for inspiration
├── samples/                    ← example scripts for testing
├── cache/                      ← HTTP/model cache (gitignored)
├── models/                     ← downloaded AI models + manifest (gitignored)
├── logs/                       ← application logs (gitignored)
└── bootstrap-manifest.json     ← written by ytfactory setup (gitignored)
```

---

## Step 12 — Local AI Model Manager (LAMM)

The Local AI Model Manager is the single authority for all local AI model lifecycle.
No feature pipeline downloads or manages models directly.

**Model registry:** `config/models-registry.yaml` — defines every local model:

| Model | Used by | Auto-download |
|---|---|---|
| `whisperx` | Subtitle alignment | Lazy (downloads on first use) |
| `silero_vad` | BGM VAD analysis | Lazy (downloads on first use) |
| `minicpm_v2_6` | Image quality review | Opt-in (requires `IMAGE_REVIEW_ENABLED=true`) |

The model manifest (`models/model-manifest.json`) persists download state across runs.

Run `ytfactory setup` after enabling a new model — LAMM provisions it automatically.

---

## Step 13 — Image Review Pipeline (Optional)

Enables per-scene AI vision quality review using MiniCPM-V 2.6 (~10 GB disk).

**Disk requirement:** ~10 GB free space for the vision model.

**Enable it in `.env`:**
```bash
IMAGE_REVIEW_ENABLED=true
VISION_REVIEW_PROVIDER=local
VISION_REVIEW_LOCAL_MODEL=minicpm_v2_6   # switch to any registry key for future models
IMAGE_REVIEW_MIN_SCORE=90
IMAGE_REVIEW_CONFIDENCE=80
IMAGE_REVIEW_MAX_ATTEMPTS=3
IMAGE_REVIEW_AUTO_REMEDIATE=true
```

Then run setup to trigger model download:
```bash
uv run ytfactory setup
```

**What it does per scene:**
1. Technical QA (file size + sharpness check)
2. Vision model review against 6 quality categories
3. On FAIL: appends targeted prompt corrections and regenerates with a new seed
4. Up to `IMAGE_REVIEW_MAX_ATTEMPTS` attempts before accepting best result

**To switch to a future vision model** — edit `config/models-registry.yaml` to add the new model, then set `VISION_REVIEW_LOCAL_MODEL=new_model_key`. No code changes needed.

---

## CLI Quick Reference

```bash
# Bootstrap & Health
ytfactory setup              # first-run setup (idempotent)
ytfactory doctor             # health check
ytfactory validate           # config + provider check only
ytfactory repair             # auto-fix missing dirs/permissions
ytfactory version            # show versions + manifest

# Full Agentic Pipeline (research → script → video)
ytfactory run "Topic" --auto

# Sequential Pipeline (manual control)
ytfactory create "Title"
ytfactory research <id>
ytfactory import-script <id> script.txt   # skip research, use own script
ytfactory plan-scenes <id>
ytfactory generate-images <id>
ytfactory generate-voice <id>
ytfactory generate-captions <id>
ytfactory render <id>
ytfactory review <id>
ytfactory remediate <id>
ytfactory publish <id>

# Or build everything at once
ytfactory build <id>

# Incremental (skip unchanged stages)
ytfactory build <id> --resume
ytfactory build <id> --force-images         # redo images + downstream
ytfactory build <id> --force-narration      # redo voice + downstream

# Scene management
ytfactory scene list <id>
ytfactory scene approve <id> --scene 3
ytfactory scene lock <id> --scene 3

# Maintenance
ytfactory clean              # wipe temp/
ytfactory clean --logs       # also wipe logs/
ytfactory reset              # clear bootstrap state
ytfactory update             # re-validate after code updates
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'kokoro'`
```bash
uv pip install kokoro soundfile
apt install espeak-ng
```

### `ModuleNotFoundError: No module named 'whisperx'`
```bash
uv pip install whisperx
```

### `GEMINI_API_KEY is empty` or `ANTHROPIC_API_KEY is empty`
- You are running from the wrong directory. Always run from the repo root.
- Or your `.env` file is missing / has empty values.

### `Settings defaults fall back to llm_provider="gemini"` (unexpected)
- You ran `ytfactory` from a subdirectory. The `.env` was not found.
- Fix: `cd /path/to/youtube-factory` then re-run.

### FFmpeg not found
```bash
sudo apt install ffmpeg
ffmpeg -version    # should print version
```

### Kokoro first run is slow
- First invocation downloads ~300 MB of model weights to `~/.cache/huggingface/`.
- Subsequent runs use the cache and start instantly.

### WhisperX alignment fails
- Ensure `WHISPERX_ENABLED=true` and `uv pip install whisperx` was run.
- The wav2vec2 model downloads on first use (~100 MB).
- If on CPU and it's slow: `WHISPERX_DEVICE=cpu` is correct but alignment takes 10–30 seconds per scene.

### BGM not playing in output video
- Check `BGM_ENABLED=true` in `.env`.
- Check `workspace/music/` has at least one `.mp3` file in the right category folder.
- Run `ytfactory doctor` to see the provider status.

### `BGM mix failed` / `Option 'hold' not found`
Occurs on FFmpeg 4.x (Ubuntu 22.04 ships **4.4.2**). The `hold` option in the `agate` filter was added in FFmpeg 5.x.

**No manual fix needed** — the pipeline auto-detects FFmpeg version at runtime and omits `hold` when not supported. BGM ducking still works; you may notice slight inter-word music pumping. To eliminate it, upgrade FFmpeg:
```bash
sudo add-apt-repository ppa:savoury1/ffmpeg5
sudo apt update && sudo apt install ffmpeg
```

> Note: If the error message shows only the FFmpeg version banner and no clear error text, check `/home/<user>/.local/share/ytfactory/` logs — the full error is in the last 800 chars of FFmpeg stderr, not the first.

### Image review fails / vision model not found
```bash
# Ensure IMAGE_REVIEW_ENABLED=true in .env, then re-run setup to trigger download
uv run ytfactory setup
```
- The model downloads ~10 GB to `~/.cache/huggingface/` on first use.
- Requires `torch` and `transformers`: `uv pip install torch transformers pillow`
- Check model status: model-manifest.json under `models/`

### `ytfactory setup` reports errors
- Fix each error one by one (they are self-explanatory).
- Re-run `ytfactory setup` after each fix — it is fully idempotent.

### Docker: API keys not loading
- The `.env` file must exist at the repo root before running `docker compose up -d`.
- The compose file bind-mounts `.env` at container startup.

### Docker: Cannot exec into container (exited)
```bash
docker compose logs youtube-factory   # see why it exited
docker compose up -d                  # restart
```

---

## Updating the Installation

After pulling new code:
```bash
git pull
uv sync                       # sync any new Python deps
uv run ytfactory update       # re-validate environment + update manifest
```

After changing `.env` provider settings:
```bash
uv run ytfactory validate     # check new provider config
```

---

## Running Tests

```bash
# All tests (fast, no API calls)
uv run pytest tests/

# Specific module
uv run pytest tests/test_bootstrap.py -v

# With keyword filter
uv run pytest -k "test_workspace"
```

---

## Notes on the Current Production Stack

The current system uses:

| Stage | Provider | Notes |
|---|---|---|
| LLM (script, research, publish) | Anthropic via LiteLLM proxy | `claude-haiku-4-5` model |
| Web search | Tavily | Used in research stage |
| Image generation | HuggingFace FLUX.1-schnell | ~30 sec/image on CPU |
| TTS | Kokoro (local) | Voice: `am_michael`, speed: 0.85 |
| Subtitle alignment | WhisperX (local) | `cpu` device |
| BGM | Local MP3 library | Sidechain ducking via FFmpeg |
| Subtitles | ASS format | Arial/DejaVu font, bottom-center |
| Output resolution | 1280×720 | YouTube HD |
| Render profile | `balanced` | Ken Burns motion + cross-dissolves |
| Pacing profile | `spiritual` | 800–2500 ms thought-block pauses |

To exactly replicate this stack, copy the settings above into your `.env`.
