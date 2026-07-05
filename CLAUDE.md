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
ytfactory review <project-id>                   # Quality review: PASS / FAIL report
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

`BuildPipeline` (`build/pipeline.py`) chains all stages in order: scenes → images → voice → captions → video → review.

### Provider System

Business logic never imports a concrete provider directly — it calls a factory function (`get_llm_provider`, `get_image_provider`, etc.) that reads `Settings` and dispatches via `match`:

| Provider type | Base class | Implementations | Setting key |
|---|---|---|---|
| LLM | `providers/llm/base.py` | Gemini | `LLM_PROVIDER` |
| Search | `providers/search/base.py` | Tavily | `SEARCH_PROVIDER` |
| Image | `providers/image/base.py` | HuggingFace, Gemini | `IMAGE_PROVIDER` |
| TTS | `providers/tts/base.py` | Edge TTS, ElevenLabs | `TTS_PROVIDER` |

To add a new provider: implement the abstract base, add a `case` in the factory, expose a setting.

### Workspace Layout

All runtime data lives in `workspace/jobs/<project-id>/` (gitignored). Each project directory has stage subdirectories populated in order:

```
workspace/jobs/<project-id>/
├── project.json       # Project domain object + stage statuses
├── research/          # research.md, research.json, sources.json
├── script/            # script.md (imported or manually written)
├── scenes/            # scene-plan.json  ← consumed by all later stages
├── images/            # scene-001.png … + manifest.json
├── audio/             # scene-001.mp3 …
├── subtitles/         # scene-001.srt …
├── video/             # scene-001.mp4 … + final.mp4
├── review/            # review-report.md, scene-review.json, review-debug.json
└── publish/
```

`scene-plan.json` is the central artifact: every downstream stage (images, voice, captions, video) reads `scenes[].visual_prompt`, `scenes[].narration`, and `scenes[].duration_seconds` from it.

### Domain Models

`src/ytfactory/domain/` holds plain dataclasses / Pydantic models (no I/O):
- `Project` — project metadata + stage status dict (stages: research, script, scenes, images, audio, subtitles, video, publish)
- `LLMResponse`, `SearchResult`, `ImageRequest` — value objects shared across providers

`ProjectRepository` (`storage/project_repository.py`) serializes `Project` to `project.json` and tracks stage status (`pending` / `running` / `completed`).

### Configuration

`Settings` (`config/settings.py`) is a Pydantic `BaseSettings` object loaded from `.env`. Copy `.env` from the example and populate API keys:

```
GEMINI_API_KEY=...
TAVILY_API_KEY=...
HF_TOKEN=...

LLM_PROVIDER=gemini
SEARCH_PROVIDER=tavily
IMAGE_PROVIDER=huggingface   # or gemini
TTS_PROVIDER=edge            # or elevenlabs
```

Image and video output default to 1920×1080 (Full HD).

### Constants

`WORKSPACE_DIR = "workspace/jobs"` and `PROJECT_FILE = "project.json"` are defined in `shared/constants.py`. All pipelines resolve paths relative to the CWD, so commands must be run from the repository root.
