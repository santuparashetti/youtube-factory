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

`BuildPipeline` (`build/pipeline.py`) chains all stages in order: scenes → images → voice → captions → video → review.

> **Gotcha:** `.gitignore` contains `build/` which inadvertently matches `src/ytfactory/build/`. Use `git add -f src/ytfactory/build/` when tracking changes there.

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

### Review Layer (Quality Gate)

`src/ytfactory/review/` is a multi-layer quality gate that runs after rendering:

**Layer 1 — Stage-based checks** (`review/stages/`): Four `BaseReviewStage` subclasses (asset_integrity, timeline, content, production_quality). Each returns a `StageResult` with `errors: list[str]` and `warnings: list[str]`.

**Layer 2 — Validation Rules** (`review/validation/`): Eight `BaseValidator` subclasses (one per category: script, narration, subtitle, image, motion, audio, rendering, story). Each rule returns a structured `ValidationResult` with rule ID, severity, evidence, confidence score, and `responsible_engine`. `ValidationRunner` orchestrates all eight; critical failures bubble into `all_errors` and affect `verdict`.

**Layer 3 — Root Cause Analysis Engine** (`review/rca/`): Consumes the `ValidationReport` to group failures by engine, build remediation chains, and detect recurring patterns. `RootCauseAnalysisEngine.analyze()` returns an `RCAReport`; `RCAReporter` writes four files.

**Layer 4 — Quality Scoring Engine** (`review/scoring/`): Converts all validation results and RCA output into objective quality scores (0–100), a letter grade (A+→F), a PASS/FAIL decision, and ranked improvement recommendations. Eight `BaseCategoryScorer` subclasses (one per validation category) use a point-budget model; `QualityScoringEngine` computes a weighted average. `QualityScoringReporter` writes four files.

**Layer 5 — Engine Feedback Loop** (`review/efl/`): Converts every RCA issue into a structured `FeedbackItem` assigned to a canonical engine target (12 engines defined in `efl/config.py`). Recurring issues get priority escalated (high→critical). `EngineFeedbackLoopEngine.generate()` returns an `EngineFeedbackReport`; `EFLReporter` writes five files including a cross-run accumulating `recurring-patterns.json`.

**Layer 6 — Video Review Debug Mode** (`review/debug/`): Captures timing and diagnostic data from every pipeline layer. Controlled by `DebugConfig(level=DebugLevel.OFF|BASIC|DETAILED|VERBOSE)` passed to `VideoQualityReviewEngine`. When not OFF, `DebugCollector` wraps each layer with `time_layer()` context managers, then `DebugReporter` writes seven files to the `review/debug/` subdirectory. Zero overhead when OFF (the default).

**Layer 7 — Auto Remediation Engine** (`review/remediation/`): Automatically repairs failed pipeline components instead of requiring a full re-run. `DecisionEngine.plan()` maps EFL feedback and RCA issues → `RemediationPlan` (deduped, sorted by severity then cost). `ProductionExecutor` deletes the failed artifact, then calls the existing idempotent pipeline to regenerate only what was deleted. `AutoRemediationEngine.remediate()` orchestrates the decision→execute→re-validate loop (up to `max_retries` cycles) stopping when `overall_score ≥ quality_threshold` (default 70). `RemediationReporter` writes four files to `workspace/jobs/<id>/remediation/`. Use `RemediationConfig(dry_run=True)` to plan without touching files.

All layers run inside `VideoQualityReviewEngine.review()` and produce a `ReviewReport` with attached `validation_report`, `rca_report`, `quality_score`, `quality_score_report`, `efl_report`, and `debug_report` dicts.

**Output files** (`review/` directory):
```
review/
├── review-report.md             # human-readable summary (all layers)
├── scene-review.json            # per-scene detail
├── review-debug.json            # full machine-readable diagnostics
├── validation-report.json       # ValidationRunner → ValidationReport
├── root-cause-report.md         # RCAReporter — human-readable RCA
├── root-cause.json              # RCAReporter — full structured report
├── engine-owner-summary.json    # RCAReporter — per-engine failure counts
├── recurring-issues.json        # RCAReporter — cross-scene patterns
├── quality-score.json           # QualityScoringReporter — overall score summary
├── quality-report.md            # QualityScoringReporter — full grade report
├── score-breakdown.json         # QualityScoringReporter — per-category detail
├── score-history.json           # QualityScoringReporter — cumulative run history
├── engine-feedback.json         # EFLReporter — full structured feedback
├── engine-feedback.md           # EFLReporter — human-readable feedback
├── engine-priority-report.json  # EFLReporter — items grouped by priority
├── recurring-patterns.json      # EFLReporter — cross-run accumulated patterns
├── improvement-roadmap.md       # EFLReporter — actionable improvement roadmap
└── debug/                       # DebugReporter — written only when debug level ≠ OFF
    ├── debug-report.md          # human-readable debug summary
    ├── debug-summary.json       # high-level JSON with verdicts/scores/diagnostics
    ├── scene-debug.json         # per-scene asset presence + validation summary
    ├── validation-debug.json    # per-rule execution data grouped by category
    ├── scoring-debug.json       # per-category scoring breakdown with weights
    ├── feedback-debug.json      # EFL feedback items for debug inspection
    └── execution-timeline.json  # ordered pipeline events with timestamps/durations

remediation/                     # RemediationReporter — written by `ytfactory remediate`
├── remediation-plan.json        # planned actions (strategy, engine, cost, status)
├── remediation-report.md        # human-readable remediation summary + cycles
├── retry-history.json           # per-action execution attempts across all cycles
└── regenerated-assets.json      # all artifacts deleted + regenerated (with backup paths)
```

### Publishing Layer (`src/ytfactory/publish/`)

`PublishPipeline.run(project_id)` is the final pipeline stage — runs after `remediate` (or `review`) and writes the complete upload-ready YouTube package to `workspace/jobs/<id>/publish/`:

| Generator | Input | Output |
|---|---|---|
| `ChaptersGenerator` | `scenes/scene-plan.json` + `audio/scene-NNN.timing.json` | `chapters.txt` |
| `TitleGenerator` | LLM + title + script excerpt | `title.txt`, `alternate-titles.txt` |
| `SEOGenerator` | LLM + title + scene titles | `keywords.txt`, `hashtags.txt`, `youtube-tags.txt` |
| `DescriptionGenerator` | LLM + chapters block + keywords | `description.md` |
| `ThumbnailGenerator` | image provider (1280×720) | `thumbnail.png`, `thumbnail-variants/` |
| `UploadPackageGenerator` | all sub-results | `youtube-metadata.json` |

`PublishConfig(skip_thumbnail=True)` skips image API calls. All LLM generators return JSON only; `_parse_json_response()` strips markdown fences and falls back to safe defaults on parse error. `ChaptersGenerator` reads real audio duration from `timing.json` last entry's `"end"` field (falls back to `scene["duration_seconds"]` if file absent).

**Debug level differences**: BASIC/DETAILED/VERBOSE all write all 7 files. BASIC omits rule-level `debug_metadata` and category scoring contributions. DETAILED adds scoring contributions. VERBOSE also includes `debug_metadata` from each validation rule.

**Scoring model**: each of the 8 categories has a fixed point budget (rules sum to 100 pts within their category); PASS=full pts, WARNING=½ pts, FAIL=0 pts, SKIP=excluded from denominator. Category raw scores are combined via weighted average (see `DEFAULT_WEIGHTS` in `review/scoring/config.py`).

**EFL engine targets**: Research Engine, Script Generation Engine, Script Pacing Engine, Speech Optimizer, TTS Engine, Scene Planner, Image Prompt Engine, Image Generation Engine, Motion Engine, ASS Subtitle Engine, Video Renderer, Video Quality Review Engine. Engine names from RCA are normalized via `ENGINE_NORMALIZATION` in `efl/config.py`.

**Human Quality Validation** (`images/human_detector.py`): `detect_human_presence(prompt)` identifies human subjects using whole-word regex matching against `_HUMAN_INDICATORS`. When a human is detected, `add_human_quality_reinforcement(prompt)` appends 7 quality phrases (highly detailed face, natural facial expression, realistic eyes, authentic skin texture, natural posture, seamless integration, documentary-quality realism). `apply_subject_dominance_rule(prompt, shot_type)` adds "subject remains visually prominent" for wide/establishing/drone shots. `ImagePipeline` retries generation (up to `settings.image_human_max_retries`) when sharpness (`compute_sharpness` via Pillow FIND_EDGES stddev) is below `settings.image_human_min_sharpness`. `HumanValidator` (category "human") in the review pipeline enforces HUM_001 (quality markers), HUM_002 (subject dominance), HUM_003 (sharpness).

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
