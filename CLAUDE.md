# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run ytfactory --help
# or equivalently
uv run python -m ytfactory --help

# Linting and formatting
uv run ruff check src/
uv run ruff format src/

# Type checking
uv run mypy src/

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_project_repository.py

# Run tests matching a keyword
uv run pytest -k "test_create"
```

## Full Video Production Workflow

### AI Research Workflow (topic → video)
```bash
ytfactory create "History of Shivaji"          # creates project slug
ytfactory research <project-id>                 # web search + LLM synthesis
# manually write or review workspace/jobs/<id>/script/script.md
ytfactory plan-scenes <project-id>              # LLM parses script → scenes
ytfactory generate-images <project-id>          # image per scene
ytfactory generate-voice <project-id>           # TTS audio per scene
ytfactory generate-captions <project-id>        # .srt per scene
ytfactory render <project-id>                   # FFmpeg: image + audio + srt → .mp4
ytfactory mix-bgm <project-id>                  # overlay background music (optional)
ytfactory overlay-cta <project-id>              # visual CTA overlay (optional, config-driven)
ytfactory review <project-id>                   # Quality review: PASS / FAIL report
ytfactory remediate <project-id>                # Auto-repair failures (dry-run safe: --dry-run)
ytfactory publish <project-id>                  # Generate YouTube publishing package
```

Or run the full pipeline at once:
```bash
ytfactory build <project-id>
```

### Existing Script Workflow
```bash
ytfactory create "My Video"
ytfactory import-script <project-id> samples/scripts/script.txt
# then continue from plan-scenes onward
```

## Architecture

### Pipeline Pattern

Each production stage is a self-contained module under `src/ytfactory/<stage>/` with a consistent internal structure:
- `pipeline.py` — the `*Pipeline` class with a `run(project_id)` method
- `cli.py` — thin Typer command that delegates to the pipeline
- `models.py` — Pydantic or dataclass models for stage artifacts
- `repository.py` — reads/writes files in the project workspace

`BuildPipeline` (`build/pipeline.py`) chains all stages in order: scenes → images → voice → captions → video → bgm → cta → review.

> **Gotcha:** `.gitignore` contains `build/` which inadvertently matches `src/ytfactory/build/`. Use `git add -f src/ytfactory/build/` when tracking changes there.

### Provider System

Business logic never imports a concrete provider directly — it calls a factory function (`get_llm_provider`, `get_image_provider`, etc.) that reads `Settings` and dispatches via `match`:

| Provider type | Base class | Implementations | Setting key |
|---|---|---|---|
| LLM | `video_core/providers/llm/base.py` | Gemini, Anthropic (OpenAI-compat), Groq, Ollama | `LLM_PROVIDER` |
| Search | `video_core/providers/search/base.py` | Tavily | `SEARCH_PROVIDER` |
| Image | `video_core/providers/image/base.py` | HuggingFace, Gemini | `IMAGE_PROVIDER` |
| TTS | `video_core/providers/tts/base.py` | Kokoro, Edge TTS | `TTS_PROVIDER` |
| Vision | `video_core/providers/vision/base.py` | Local (Qwen2.5-VL via llama.cpp), Mock | `VISION_REVIEW_PROVIDER` |

Base classes and factory functions live in `video_core.providers.*` as of Phase 0 (2026-07-12). Product-specific implementations (e.g. the Contemplative Pacing Engine) remain in `ytfactory.providers.tts.pacing`. LAMM (Local AI Model Manager) lives in `src/video_core/models/`.

**Layering rule:** `video_core` must never import from `ytfactory`. Enforce with `python3 scripts/check_layering.py`. One remaining Bucket-C exception: `ytfactory.shared.constants` (WORKSPACE_DIR — deferred to Phase 2). `ytfactory.config.settings` resolved by Phase 1.

To add a new provider: implement the abstract base, add a `case` in the factory, expose a setting.

### Workspace Layout

All runtime data lives in `workspace/jobs/<project-id>/` (gitignored). Each project directory has stage subdirectories populated in order:

```
workspace/jobs/<project-id>/
├── project.json       # Project domain object + stage statuses
├── research/          # research.md, research.json, sources.json
├── script/            # script.md (imported or manually written)
├── scenes/            # scene-plan.json  ← consumed by all later stages
├── images/            # scene-001.png … + manifest.json + needs-review-NNN.json (QA exhausted-FAIL flag)
├── audio/             # scene-001.mp3 …
├── subtitles/         # scene-001.srt …
├── video/             # scene-001.mp4 … + final.mp4 (+ final.pre-cta.mp4 when CTA applied)
├── cta/               # cta-timing.json, cta-review-report.json
├── review/            # All quality gate outputs (see below)
├── remediation/       # Auto Remediation Engine outputs
└── publish/           # YouTube publishing package (see Publishing Layer below)
    ├── thumbnail.png                  # 1280×720 primary thumbnail
    ├── thumbnail-variants/            # variant-1.png … variant-3.png
    ├── title.txt                      # primary YouTube title
    ├── alternate-titles.txt           # 5 alternatives (one per line)
    ├── description.md                 # full YouTube description
    ├── keywords.txt                   # all keywords (one per line)
    ├── hashtags.txt                   # #hashtags (one per line)
    ├── youtube-tags.txt               # tags (comma-separated)
    ├── chapters.txt                   # timestamp chapters
    └── youtube-metadata.json          # structured metadata (all sub-results)
```

`scene-plan.json` is the central artifact: every downstream stage (images, voice, captions, video) reads `scenes[].visual_prompt`, `scenes[].narration`, and `scenes[].duration_seconds` from it.

**Scene planner idempotency patch:** `scene_planner_node` (`agents/nodes/scene_planner.py`) caches the plan and returns early if `scene-plan.json` already exists. The early-return block also defensively strips any H1 heading that leaked into scene 1's narration from older runs. If scene 1 narration was corrupted (title text concatenated into spoken content), delete `audio/scene-001.mp3`, `subtitles/scene-001.srt`, and `video/scene-001.mp4`, then re-run `generate-voice → generate-captions → render` — the cached plan will be auto-patched on the next pipeline run without a full re-plan.

### Review Layer (Quality Gate)

`src/ytfactory/review/` — 7-layer quality gate (stage checks → validation rules → RCA → quality scoring → engine feedback loop → debug mode → auto remediation). Runs after `ytfactory render`.

- ValidationRunner runs **12 validators**: script, narration, subtitle, image, human, motion, audio, rendering, story, bgm, vision_review, cta
- `RemediationAction` requires `confidence: int` and `rationale: str` fields (not optional)
- `DebugConfig(level=DebugLevel.OFF)` by default — zero overhead; BASIC/DETAILED/VERBOSE write 7 files to `review/debug/`
- Scoring: PASS=full pts, WARNING=½ pts, FAIL=0 pts, SKIP=excluded; 8 category scorers → weighted 0–100 + letter grade
- EFL: 12 engine targets; names normalized via `ENGINE_NORMALIZATION` in `efl/config.py`
- **"human" NOT in `_HUMAN_INDICATORS`** — avoid false positive with "natural human anatomy"
- Output: `workspace/jobs/<id>/review/` — 17+ files; `remediation/` — 4 files

### Image Review Layer (`src/ytfactory/images/`)

Per-scene vision QA gate runs during `generate-images` (both LangGraph and direct pipeline paths). Controlled by `ImageReviewConfig` (from `images/review_config.py`).

- Active model: **Qwen2.5-VL-3B** (`qwen2_5_vl_3b`, ~3 GB disk); set via `VISION_REVIEW_LOCAL_MODEL`
- **Provider caching:** vision model and Kokoro TTS are loaded once at module level in `scene_assets.py` (`_get_vision_provider`, `_get_tts_provider`) and shared across all parallel scene nodes. Never call `get_vision_provider()`/`get_tts_provider()` directly inside scene nodes — always use the cached wrappers to avoid per-scene reloads and OOM
- `IMAGE_HAND_AVOIDANCE_CHECK_ENABLED=true` (default) — extra vision check for visible hands in back-view/profile scenes; only fires when `IMAGE_REVIEW_ENABLED=true`
- On exhausted retries with FAIL: writes `images/needs-review-NNN.json` flag and emits `logger.error` — scene is NOT blocked but flagged for manual inspection
- QA gate order per attempt: specialist review → human QA → hand-presence check; refinement priority: `hand_presence > human_qa > specialist > overall`

### Publishing Layer (`src/ytfactory/publish/`)

Runs after `remediate` (or `review`). Generators: ChaptersGenerator, TitleGenerator, SEOGenerator, DescriptionGenerator, **PinnedCommentGenerator**, ThumbnailGenerator, UploadPackageGenerator.
Output: `workspace/jobs/<id>/publish/` — 10 files (includes `pinned-comment.txt`, `youtube-metadata.json`).
`PublishConfig(skip_thumbnail=True)` skips image API calls. When adding LLM mock side_effects in publish tests, include a **4th response** for the pinned comment call.
`ChaptersGenerator` reads audio duration from `timing.json` last `"end"` field (falls back to `scene["duration_seconds"]`). Produces at most `publish_max_chapters` (default 10) chapters, merging adjacent scenes into even contiguous groups when there are more natural scene boundaries than the cap. Short videos get fewer chapters — never padded up to the cap. Minimum chapter length `publish_min_chapter_seconds` (default 10s, matching YouTube's own rule) is enforced; if merging to the cap still leaves a chapter below this threshold, groups are merged further (which may produce fewer than the cap).

### Domain Models

Generic provider I/O shapes (`LLMResponse`, `SearchResult`, `ImageRequest`) live in `src/video_core/domain/`. Factory-specific models (`Project` + stage-status dict, `AudioRequest`, `SceneRequest`, etc.) stay in `src/ytfactory/domain/`. `ProjectRepository` (`storage/project_repository.py`) → `project.json`; statuses: `pending` / `running` / `completed`.

### Configuration

`Settings` (`config/settings.py`) is a Pydantic `BaseSettings` object loaded from `.env`. Copy `.env` from the example and populate API keys:

```
GEMINI_API_KEY=...
TAVILY_API_KEY=...
HF_TOKEN=...

LLM_PROVIDER=anthropic
SEARCH_PROVIDER=tavily
IMAGE_PROVIDER=huggingface   # or gemini
TTS_PROVIDER=kokoro          # or edge
```

Image output defaults to 1280×720 (HD 720p).

`Settings` is split as of Phase 1 (2026-07-12): `video_core.config.SharedSettings` holds credentials/provider config; `ytfactory.config.Settings` extends it with pipeline-specific fields. Both load from this same `.env` — no workflow change for local development.

### Constants

`WORKSPACE_DIR = "workspace/jobs"` and `PROJECT_FILE = "project.json"` are defined in `shared/constants.py`. All pipelines resolve paths relative to the CWD, so commands must be run from the repository root.

### Test Patterns

Tests live in `tests/`. API-dependent files (`test_gemini_image.py`, `test_hf_image.py`) sit at the repo root and require live keys; run only the `tests/` directory to avoid them:

```bash
uv run pytest tests/
```

When testing code that uses `WORKSPACE_DIR` (review engine, reporter, artifacts), patch the module-level binding in the consuming module, not in `shared.constants`:

```python
monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))
monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
```
