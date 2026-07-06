# MASTER_CONTEXT_V2.md

# YouTube Factory — Master Project Context (V2)

> **Purpose:** Canonical project memory for YouTube Factory. Any new Claude Code session
> should read this document before reading feature-specific specifications. This supersedes
> `MASTER_CONTEXT_V1.md`.

---

## 1. Project Vision

Build a production-grade AI-powered pipeline that automatically generates premium
documentary/spiritual YouTube videos with minimal manual effort.

**Core principles:**
- Documentary-quality storytelling and cinematic visuals
- Natural narration with contemplative pacing
- Professional subtitles (ASS format) with typography intelligence
- Cultural and historical authenticity in every visual
- Human subject quality enforcement at both generation and review time
- Modular, provider-agnostic architecture — each component is swappable
- Self-healing: quality gate → root cause → auto-remediation loop

---

## 2. Repository Layout

```
youtube-factory/
├── src/ytfactory/          # all production code (installed as `ytfactory` package)
├── tests/                  # pytest suite — run from repo root
├── workspace/jobs/         # gitignored runtime data (one dir per project)
├── workspace/music/        # BGM library: <category>/*.mp3
├── docs/                   # specs and context documents
│   ├── context/            # this file + V1 + sprint context
│   ├── image-prompt-generation/
│   ├── video-quality-review/
│   ├── video/
│   ├── tts/
│   └── script/
├── samples/scripts/        # sample scripts for testing import
├── CLAUDE.md               # project instructions for Claude Code
└── pyproject.toml          # uv project config
```

**Critical .gitignore gotcha:** `build/` in `.gitignore` inadvertently matches
`src/ytfactory/build/`. Use `git add -f src/ytfactory/build/` when tracking changes there.

---

## 3. Commands

```bash
uv sync                                         # install dependencies
uv run ytfactory --help                         # CLI help
uv run ruff check src/ && uv run ruff format src/  # lint + format
uv run mypy src/                                # type checking
uv run pytest tests/                            # all tests (1317 passing as of 2026-07-06)
uv run pytest tests/test_project_repository.py # single file
uv run pytest -k "test_create"                  # filter by name
```

---

## 4. Full Pipeline — Stage by Stage

### 4.1 CLI Workflow (command per stage)

```bash
ytfactory create "History of Shivaji"   # creates project slug
ytfactory research <project-id>          # web search + LLM synthesis
# (manually write or review workspace/jobs/<id>/script/script.md)
ytfactory plan-scenes <project-id>       # LLM parses script → scenes
ytfactory generate-images <project-id>   # image per scene
ytfactory generate-voice <project-id>    # TTS audio per scene
ytfactory generate-captions <project-id> # .srt/.ass per scene
ytfactory render <project-id>            # FFmpeg: image + audio + srt → .mp4
ytfactory review <project-id>            # Quality review: PASS / FAIL report
ytfactory remediate <project-id>         # Auto-repair failures (--dry-run safe)
ytfactory publish <project-id>           # YouTube publishing package
ytfactory build <project-id>             # full pipeline in one command
```

### 4.2 Internal Pipeline Chain (what `build` does)

```
ResearchPipeline
→ ScriptPipeline (ScriptEnhancer agent)
→ ScenePipeline (plan-scenes)
→ ImagePipeline (generate-images, with human quality retry)
→ VoicePipeline (TTS + pacing)
→ CaptionPipeline (ASS subtitles)
→ VideoPipeline (FFmpeg render + BGM mix)
→ ReviewPipeline (7-layer quality gate)
→ RemediationPipeline (auto-repair)
→ PublishPipeline (YouTube package)
```

`BuildPipeline` (`build/pipeline.py`) chains all these in order.

### 4.3 Agent Graph (alternative to CLI — LangGraph-style)

`agents/graph.py` defines a LangGraph-compatible DAG of nodes:
`research → script_writer → script_enhancer → scene_planner → scene_assets → video_renderer → video_concatenator → quality_review → human_review → remediation → publish`

Each node in `agents/nodes/` delegates to the matching pipeline.

---

## 5. Architecture Principles

### 5.1 Pipeline Pattern

Every stage lives in `src/ytfactory/<stage>/` with a consistent internal shape:
- `pipeline.py` — `*Pipeline` class with `run(project_id: str)` method
- `cli.py` — thin Typer command that delegates to the pipeline
- `models.py` — Pydantic/dataclass models for stage artifacts
- `repository.py` — reads/writes files in the project workspace

### 5.2 Provider System

Business logic never imports concrete providers — it calls a factory function
(`get_llm_provider`, `get_image_provider`, etc.) that reads `Settings` and dispatches:

| Provider type | Base class | Implementations | Setting key |
|---|---|---|---|
| LLM | `providers/llm/base.py` | Gemini, Groq, OpenAI, Ollama | `LLM_PROVIDER` |
| Search | `providers/search/base.py` | Tavily | `SEARCH_PROVIDER` |
| Image | `providers/image/base.py` | HuggingFace, Gemini, Pollinations, A1111, Mock | `IMAGE_PROVIDER` |
| TTS | `providers/tts/base.py` | Edge TTS, ElevenLabs | `TTS_PROVIDER` |

To add a new provider: implement the abstract base, add a `case` in the factory,
expose a setting in `Settings`.

**Provider capability split for image anatomy:** Only
`{"huggingface", "a1111", "automatic1111", "sd-webui"}` support negative prompts
(`_PROVIDERS_WITH_NEGATIVE_PROMPTS` in `prompt_engine.py`). Others (pollinations,
gemini) get positive anatomy reinforcement appended to the prompt instead.

### 5.3 Workspace Layout

All runtime data lives in `workspace/jobs/<project-id>/` (gitignored):

```
workspace/jobs/<project-id>/
├── project.json           # Project domain object + stage statuses
├── research/              # research.md, research.json, sources.json
├── script/                # script.md (imported or manually written)
├── scenes/                # scene-plan.json  ← central artifact
├── images/                # scene-001.png … + manifest.json
├── audio/                 # scene-001.mp3 …
├── subtitles/             # scene-001.srt / scene-001.ass …
├── video/                 # scene-001.mp4 … + final.mp4
├── review/                # quality gate outputs (see §8)
├── remediation/           # auto remediation outputs
└── publish/               # YouTube publishing package (see §11)
```

`scene-plan.json` is the **central artifact**: every downstream stage reads
`scenes[].visual_prompt`, `scenes[].narration`, and `scenes[].duration_seconds`.

### 5.4 Test Patterns

When patching `WORKSPACE_DIR` in tests, patch the binding in the consuming module,
not in `shared.constants`:

```python
monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))
monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
```

---

## 6. Configuration (Settings)

`Settings` (`config/settings.py`) is a Pydantic `BaseSettings` loaded from `.env`.

**Key settings reference:**

```
# API Keys
GEMINI_API_KEY, TAVILY_API_KEY, HF_TOKEN, GROQ_API_KEY, ANTHROPIC_API_KEY

# Providers (defaults)
LLM_PROVIDER=gemini
SEARCH_PROVIDER=tavily
IMAGE_PROVIDER=pollinations
TTS_PROVIDER=edge

# Models
GEMINI_TEXT_MODEL=gemini-2.5-flash
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
HF_IMAGE_MODEL=black-forest-labs/FLUX.1-schnell

# Image / Video
IMAGE_WIDTH=1920, IMAGE_HEIGHT=1080
VIDEO_WIDTH=1920, VIDEO_HEIGHT=1080, VIDEO_FPS=30
RENDER_PROFILE=balanced   # draft | balanced | cinematic | premium

# Human Quality Validation
IMAGE_HUMAN_MAX_RETRIES=2          # retry loop for blurry human scenes
IMAGE_HUMAN_MIN_SHARPNESS=12.0    # pipeline retry threshold (Pillow edge stddev)

# TTS / Pacing
TTS_PROVIDER=edge
TTS_PACING_ENABLED=true
TTS_PACING_PROFILE=spiritual   # normal|documentary|spiritual|meditation|slow_reflection
TTS_MAX_RETRIES=3

# BGM (opt-in)
BGM_ENABLED=false
BGM_CATEGORY=auto              # auto|spiritual|meditation|cinematic_ambient|…
BGM_LIBRARY_PATH=workspace/music
BGM_VOLUME=0.20
BGM_DUCK_THRESHOLD=0.02
BGM_DUCK_RATIO=4.0

# Subtitles (ASS)
SUBTITLE_FORMAT=ass
SUBTITLE_ASS_THEME=default     # default|minimal|high_contrast|cinematic
SUBTITLE_ASS_FONT=Arial
SUBTITLE_ASS_FONT_SIZE=52
SUBTITLE_ASS_PRIMARY_COLOR=&H00FFFFFF  (white)

# Video encoding
VIDEO_CRF=23
VIDEO_PRESET=medium
VIDEO_INTRO_ENABLED=true
VIDEO_INTRO_SECONDS=1.5
```

**Policy:** when changing `.env`, comment out the old value and put the new value
on the next line — never overwrite in place.

---

## 7. Image Pipeline — Full Stack

### 7.1 Image Prompt Engine V5 (class `ImagePromptEngineV4` for backward compat)

File: `src/ytfactory/images/prompt_engine.py`

**Pipeline inside `enrich_for_provider(scenes, provider)`:**
1. Shot type from `ShotPlanner`
2. Cliché detection + replacement
3. Unsafe composition filtering
4. Human quality reinforcement (`human_detector.py`) — runs BEFORE provider step
5. Subject Dominance Rule (wide shots with humans)
6. Provider-specific anatomy/negative prompt step

**`review_prompt(scenes)`** checks all prompts for issues including:
- Forbidden words (logo, text, watermark, etc.)
- Human scenes missing quality markers

Debug output (when `IMAGE_PROMPT_DEBUG=true`): per-scene files in `images/debug/`.

### 7.2 Human Quality Validation V1

File: `src/ytfactory/images/human_detector.py`

**Core functions:**

```python
detect_human_presence(prompt: str) -> bool
    # Uses whole-word regex \bINDICATOR\b for all indicators
    # "human" is NOT in _HUMAN_INDICATORS (would match anatomy phrase)
    # "surface" does NOT match "face"

has_human_quality_reinforcement(prompt: str) -> bool
    # Requires ≥ 2 of the 7 _HUMAN_QUALITY_MARKERS sub-phrases to be present
    # Markers are non-overlapping to prevent double-counting

add_human_quality_reinforcement(prompt: str) -> str
    # Idempotent — skips if already reinforced
    # Appends: ", highly detailed human face, natural facial expression, realistic eyes,
    #   authentic skin texture, natural posture, seamless integration with the environment,
    #   documentary-quality realism"

apply_subject_dominance_rule(prompt: str, shot_type: str = "") -> str
    # Appends ", subject remains visually prominent and detailed despite wide framing"
    # Only when: human detected AND shot_type in wide/establishing/drone/high-angle
    # Idempotent — skips if hint already present

compute_sharpness(image_path: Path) -> float
    # Pillow FIND_EDGES stddev on 512×288 downsample — no numpy
    # < 8 = blurry, 8–15 = marginal, > 15 = sharp
    # Returns 0.0 on any error
```

**_HUMAN_INDICATORS** (44 words, all whole-word matched):
Demographic: man, woman, person, people, child, children, boy, girl, elder, baby
Occupational: monk, warrior, farmer, leader, soldier, scholar, ruler, priest, guru, sage, philosopher, king, queen, emperor, mother, father, villager, peasant, merchant, artisan
Physical: face, portrait
Social: crowd, audience

**Two-threshold design:**
- Pipeline retry: `image_human_min_sharpness = 12.0` (Settings) — aggressive, retries up to `image_human_max_retries=2` times
- Validator HUM_003: threshold `8.0` — catches only genuinely blurry images that slipped through

**Sharpness retry loop** in `images/pipeline.py`:
After generation, if human detected and retries > 0: compute sharpness; if below threshold, delete and regenerate; repeat up to max_retries; warn if still below threshold after all retries.

**Diagnostics tracking** (`images/diagnostics.py`):
`DiagnosticsReport` tracks `human_scenes_count`, `human_quality_enforced`, `human_quality_missing: list[int]`.
`build_report()` imports from `human_detector` and populates all three; adds an issue string when `human_quality_missing` is non-empty.

**Test coverage:** `tests/test_human_quality_validation.py` — 47 tests across 9 classes covering detection, markers, reinforcement, dominance, sharpness, and HUM_001/002/003 rules.

### 7.3 Known Design Decisions / Gotchas

| Decision | Reason |
|---|---|
| "human" excluded from `_HUMAN_INDICATORS` | Anatomy reinforcement phrase "natural human anatomy" contains "human" — would cause false detection on second pass |
| All indicators use `\bINDICATOR\b` | "surface" must not match "face"; "natural" must not match "man" |
| `_HUMAN_QUALITY_MARKERS` are non-overlapping | Prevents substring double-counting ("facial expression" ⊂ "natural facial expression") |
| Reinforcement requires ≥ 2 markers | Single-marker partial matches (e.g. from user-written prompts) don't count as fully reinforced |
| Pipeline threshold (12.0) > validator threshold (8.0) | Pipeline retries aggressively; validator only flags genuinely poor results |

---

## 8. Review Layer — 7-Layer Quality Gate

Entry point: `VideoQualityReviewEngine.review()` in `review/engine.py`

### Layer 1 — Stage-based checks (`review/stages/`)

Four `BaseReviewStage` subclasses: `AssetIntegrityStage`, `TimelineStage`,
`ContentStage`, `ProductionQualityStage`. Each returns `StageResult` with
`errors: list[str]` and `warnings: list[str]`.

### Layer 2 — Validation Rules (`review/validation/`)

**10 validators** run in this order via `ValidationRunner`:

| # | Validator | Category | Key rules |
|---|---|---|---|
| 1 | ScriptValidator | script | word count, filler %, sentence density |
| 2 | NarrationValidator | narration | words/min pace, silence gaps |
| 3 | SubtitleValidator | subtitle | CPS, line count, timing sync |
| 4 | ImageValidator | image | file exists, resolution, format |
| 5 | HumanValidator | human | HUM_001 (quality markers), HUM_002 (dominance), HUM_003 (sharpness) |
| 6 | MotionValidator | motion | motion type presence, profile match |
| 7 | AudioValidator | audio | file presence, duration match, volume levels |
| 8 | RenderingValidator | rendering | black frames, encoding params, file size |
| 9 | StoryValidator | story | narrative arc, hook, closing |
| 10 | BGMValidator | bgm | BGM presence when enabled, audio levels |

**BaseValidator pattern:** ABC with `_pass()`, `_fail()`, `_warn()`, `_skip()` helpers
accepting `**meta` kwargs that land in `debug_metadata`.

**ValidationResult** fields: `rule_id, category, status, severity, description,
evidence, confidence, responsible_engine, timestamp, debug_metadata`.

**Scoring model:** each category has a fixed point budget (rules sum to 100 pts);
PASS=full pts, WARNING=½ pts, FAIL=0 pts, SKIP=excluded from denominator.

### Layer 3 — Root Cause Analysis (`review/rca/`)

`RootCauseAnalysisEngine.analyze()` consumes `ValidationReport`:
- Groups failures by engine
- Builds remediation chains
- Detects recurring cross-scene patterns
- Produces `RCAReport`; `RCAReporter` writes 4 files

**Analyzers:** `script, narration, subtitle, image, motion, audio, rendering, story`
(one per validation category, in `review/rca/analyzers/`)

### Layer 4 — Quality Scoring (`review/scoring/`)

Converts all validation results + RCA output into objective scores (0–100).

**Category weights (DEFAULT_WEIGHTS, must sum to 1.0):**

| Category | Weight |
|---|---|
| rendering | 0.20 |
| narration | 0.15 |
| image | 0.15 |
| audio | 0.15 |
| subtitle | 0.10 |
| script | 0.10 |
| motion | 0.10 |
| storytelling | 0.05 |

**Grade scale:** A+ ≥ 95, A ≥ 90, B ≥ 80, C ≥ 70, D ≥ 60, F < 60

**PASS threshold:** overall_score ≥ 70.0 (configurable via `QualityScoringConfig`)

**8 `BaseCategoryScorer` subclasses** (one per category) in `review/scoring/scorers/`.
`QualityScoringEngine` computes weighted average; `QualityScoringReporter` writes 4 files.

### Layer 5 — Engine Feedback Loop (`review/efl/`)

Converts every RCA issue into a `FeedbackItem` assigned to one of 12 canonical
engine targets. Recurring issues (≥ 2 occurrences) get priority escalated.

**12 canonical engine targets:**
Research Engine, Script Generation Engine, Script Pacing Engine, Speech Optimizer,
TTS Engine, Scene Planner, Image Prompt Engine, Image Generation Engine, Motion Engine,
ASS Subtitle Engine, Video Renderer, Video Quality Review Engine.

`ENGINE_NORMALIZATION` in `efl/config.py` maps RCA engine strings to canonical names.
`EFLReporter` writes 5 files including cross-run accumulating `recurring-patterns.json`.

### Layer 6 — Debug Mode (`review/debug/`)

Controlled by `DebugConfig(level=DebugLevel.OFF|BASIC|DETAILED|VERBOSE)`.
Zero overhead when OFF (the default).

When active: `DebugCollector` wraps each layer with `time_layer()` context managers;
`DebugReporter` writes 7 files to `review/debug/`.

**Level differences:** BASIC omits rule-level `debug_metadata` and category scoring
contributions. DETAILED adds scoring contributions. VERBOSE adds full `debug_metadata`
from each validation rule.

### Layer 7 — Auto Remediation (`review/remediation/`)

`AutoRemediationEngine.remediate()` orchestrates: plan → execute → re-validate loop
(up to `max_retries=3` cycles) stopping when `overall_score ≥ quality_threshold=70`.

**6 strategies (cheapest → most expensive):**

| Strategy | Cost | Description |
|---|---|---|
| retry_validation | 0.0 | re-run validation, no regeneration |
| regenerate_subtitles | 0.1 | delete + regenerate subtitle files |
| regenerate_audio | 0.5 | delete + regenerate audio + timing |
| regenerate_image | 1.0 | delete + regenerate scene image |
| regenerate_video_clip | 0.3 | delete + re-render scene clip |
| full_regeneration | 10.0 | wipe all artifacts and rebuild |

**Engine → strategy mapping** in `remediation/config.py` (`ENGINE_STRATEGY_MAP`):
e.g. Image Prompt Engine → regenerate_image; ASS Subtitle Engine → regenerate_subtitles.

`RemediationConfig(dry_run=True)` plans without touching files.
`ProductionExecutor` deletes the failed artifact then calls the existing idempotent
pipeline to regenerate only what was deleted.
`RemediationReporter` writes 4 files to `workspace/jobs/<id>/remediation/`.

### Review Output Files

```
review/
├── review-report.md             # human-readable summary (all layers)
├── scene-review.json            # per-scene detail
├── review-debug.json            # full machine-readable diagnostics
├── validation-report.json       # ValidationRunner → ValidationReport
├── root-cause-report.md         # human-readable RCA
├── root-cause.json              # full structured RCA report
├── engine-owner-summary.json    # per-engine failure counts
├── recurring-issues.json        # cross-scene patterns
├── quality-score.json           # overall score summary
├── quality-report.md            # full grade report
├── score-breakdown.json         # per-category detail
├── score-history.json           # cumulative run history
├── engine-feedback.json         # full structured EFL feedback
├── engine-feedback.md           # human-readable feedback
├── engine-priority-report.json  # items grouped by priority
├── recurring-patterns.json      # cross-run accumulated patterns (EFL)
├── improvement-roadmap.md       # actionable improvement roadmap
└── debug/                       # written only when debug level ≠ OFF
    ├── debug-report.md
    ├── debug-summary.json
    ├── scene-debug.json
    ├── validation-debug.json
    ├── scoring-debug.json
    ├── feedback-debug.json
    └── execution-timeline.json

remediation/
├── remediation-plan.json
├── remediation-report.md
├── retry-history.json
└── regenerated-assets.json
```

---

## 9. Scene Planning — Cultural & Visual Intelligence

### 9.1 Scene Planner (LLM-based)

Entry: `ytfactory plan-scenes <id>` → `ScenePipeline` → `GeminiPlanner` →
calls LLM with `_VISUAL_PROMPTS_TEMPLATE` from `agents/prompts/scene_planner.py`

The template is extensive. Key sections in order:

**BANNED section:**
- Common imagery clichés (glowing brain, etc.)
- Anatomy safety rules
- Cultural Mixing ban (added this session)

**CULTURAL AUTHENTICITY section (added 2026-07-06):**
7 cultural contexts mapped to their authentic visual elements:

| Context | Visual elements |
|---|---|
| Ancient Indian philosophy | sages, ashrams, ghats, banyan/peepal trees, dhotis, diyas, Sanskrit manuscripts |
| Contemporary / Modern life | city streets, offices, smartphones, contemporary clothing |
| Ancient Greek | marble colonnades, tunics/himation, agora, olive groves, pottery |
| East Asian Buddhist/Daoist | wooden temples, bamboo, rock gardens, grey robes, ink paintings |
| Islamic / Middle Eastern | muqarnas arches, geometric tiles, medinas, flowing robes, calligraphy |
| Medieval European | stone castles, torchlit halls, armour, illuminated manuscripts |
| Sub-Saharan African | savanna, baobabs, earthen architecture, kente fabric, communal fires |

Rule: universal/timeless narration → default to contemporary unless script implies
otherwise.

**HUMAN SUBJECT QUALITY section:** instructs LLM to always include all 7 quality
markers for human subjects, plus subject dominance phrase for wide shots.

**PER-SCENE INTERNAL REASONING (10 steps A–J):**

- **Step A (new, gates all others):** Identify cultural context and era from narration.
  Confirm: environment, clothing, and objects all belong to this one culture.
- Step B: Shot type selection (story vs. coverage shot)
- Step C: Scene type (generated vs. asset)
- Step D: Character consistency
- Step E: Avoid clichés
- Step F: Composition rules
- Step G: Colour/light palette
- Step H: Motion type
- Step I: Duration estimate
- **Step J:** Final check — confirm cultural authenticity from step A

### 9.2 Shot Planner

`images/shot_planner.py` — assigns shot types from a defined vocabulary.
Wide shot types: `{"wide shot", "establishing shot", "drone", "wide cinematic", "high angle"}`.
These trigger the Subject Dominance Rule in `human_detector.py`.

---

## 10. TTS & Voice Pipeline

### 10.1 Architecture

`VoicePipeline` → provider (Edge TTS or ElevenLabs) via `get_tts_provider()`.

The narration text for each scene passes through:
1. **SpeechOptimizer** — spoken-language optimization, natural delivery, pause hints
2. **SpeechFormatter** — SSML/provider-specific formatting
3. **EmotionEngine** — maps scene emotion tags to TTS prosody parameters
4. **Contemplative Pacing Engine** (`providers/tts/pacing/`) — injects silence between
   sentences via FFmpeg concat; profile controls pause ranges
5. **Audio validator** — checks file size, duration, word-count ratio
6. **Auto-retry** — up to `tts_max_retries=3` with exponential backoff

Pacing profiles (from `TTS_PACING_PROFILE` setting):
`normal | documentary | spiritual | meditation | slow_reflection`

The `spiritual` profile inserts: 500–700 ms normal pause, 1.2–1.8 s important pause,
2.0–2.5 s major-realization pause.

### 10.2 Audio output files

```
audio/
├── scene-001.mp3
├── scene-001.timing.json    # word/sentence timestamps (used by ChaptersGenerator)
└── …
```

---

## 11. ASS Subtitle Engine

`subtitles/` module produces professional ASS (Advanced SubStation Alpha) subtitles.

Key components:
- `engine.py` — main subtitle generation logic
- `segmenter.py` — splits narration into display segments
- `timing.py` — maps segments to audio timestamps
- `ass/writer.py` — ASS file construction
- `ass/theme_manager.py` — theme presets (default, minimal, high_contrast, cinematic)
- `ass/style_builder.py` — builds ASS `[V4+ Styles]` section from Settings
- `typography.py` — line breaking rules (max 42 chars/line, 2 lines/cue)
- `validator.py` — enforces Netflix/BBC standards (≤18 CPS, ≤42 chars, ≤2 lines)

Output: `scene-NNN.ass` (primary) + `scene-NNN.srt` (compatibility fallback).

---

## 12. Cinematic Motion & Video Rendering

### 12.1 Cinematic Motion Engine (`cinematic/`)

`MotionPlanner` assigns motion effects per scene based on emotion and render profile:
- `draft` — static frame, hard cuts
- `balanced` — simple zoompan, cross-dissolves
- `cinematic` — emotion-aware motion, ease_in_out
- `premium` — wider scale ranges, longer fades

Components: `motion.py`, `effects.py`, `transitions.py`, `profiles.py`

### 12.2 Video Pipeline (`video/pipeline.py`)

`VideoPipeline.run(project_id)`:
1. Renders per-scene clips: FFmpeg with image + audio + ASS subtitle burn-in
2. Adds cinematic intro (1.5 s black screen when `VIDEO_INTRO_ENABLED=true`)
3. Concatenates via FFmpeg concat demuxer
4. Applies BGM mixing when `BGM_ENABLED=true`

**BGM integration:** BGM mixing is the final step of `VideoPipeline.run()`, applied
immediately after concatenation. This means all code paths that call `VideoPipeline`
(including `ProductionExecutor` during remediation) produce a BGM-mixed `final.mp4`.

**Encoding defaults:** H.264 CRF=23, preset=medium, no tune, keyframe every 60 frames,
128k AAC audio.

---

## 13. BGM System (`bgm/`)

BGM is opt-in (`BGM_ENABLED=false` by default).

**Components:**
- `detector.py` — detects video topic/mood to select BGM category
- `library.py` — scans `workspace/music/<category>/*.mp3`; random track selection
- `mixer.py` — FFmpeg-based: loop/trim track to video length, apply ducking sidechain
  under narration, fade in/out
- `pipeline.py` — standalone pipeline (primarily for testing)
- `config.py` — `BGMConfig` dataclass

**Ducking:** sidechain compress (threshold=0.02, ratio=4.0, attack=200ms, release=1000ms)
so BGM volume automatically drops under speech.

---

## 14. Script Enhancement

`agents/prompts/script_enhancer.py` — used when user imports an existing script that
is too short for the target duration.

**7-priority expansion order (exhausted in sequence):**
1. Pacing / silence — add contemplative pauses
2. Depth — expand thin explanations with more detail
3. Examples — add concrete relatable examples
4. Context — add historical or philosophical background
5. Story — add narrative moments or character detail
6. Transition — smooth between sections
7. New content — add new thematic content (last resort)

**Style voices:** `spiritual | documentary | history | educational`
(selectable, affects tone and structure guidance)

**Branding frame:** Atma Theory intro/closing appended as a non-rewritable frame.

---

## 15. Publishing Layer (`publish/`)

`PublishPipeline.run(project_id)` runs after `remediate` (or `review`) and writes
the complete upload-ready YouTube package to `workspace/jobs/<id>/publish/`.

| Generator | Input | Output |
|---|---|---|
| `ChaptersGenerator` | `scene-plan.json` + `audio/scene-NNN.timing.json` | `chapters.txt` |
| `TitleGenerator` | LLM + title + script excerpt | `title.txt`, `alternate-titles.txt` |
| `SEOGenerator` | LLM + title + scene titles | `keywords.txt`, `hashtags.txt`, `youtube-tags.txt` |
| `DescriptionGenerator` | LLM + chapters block + keywords | `description.md` |
| `ThumbnailGenerator` | image provider (1280×720) | `thumbnail.png`, `thumbnail-variants/` |
| `UploadPackageGenerator` | all sub-results | `youtube-metadata.json` |

`PublishConfig(skip_thumbnail=True)` skips image API calls.
`ChaptersGenerator` reads real audio duration from `timing.json` last entry's `"end"` field
(falls back to `scene["duration_seconds"]` if file absent).
All LLM generators return JSON only; `_parse_json_response()` strips markdown fences.

---

## 16. Completed V1 Specifications

All these specs are fully implemented and tested:

| Spec | Location | Status |
|---|---|---|
| IMAGE_PROMPT_ENGINE_V4 | `docs/image-prompt-generation/IMAGE_PROMPT_ENGINE_V4.md` | ✅ |
| HUMAN_QUALITY_AND_SUBJECT_VALIDATION_V1 | `docs/image-prompt-generation/HUMAN_QUALITY_AND_SUBJECT_VALIDATION_V1.md` | ✅ |
| SCRIPT_GENERATION_RULES_V1 | `docs/script/SCRIPT_GENERATION_RULES_V1.md` | ✅ |
| SCRIPT_BRANDING_V1 | `docs/script/SCRIPT_BRANDING_V1.md` | ✅ |
| SCRIPT_PACING_AND_DURATION_RULES_V2 | `docs/script/SCRIPT_PACING_AND_DURATION_RULES_V2.md` | ✅ |
| SPEECH_OPTIMIZER_V1 | `docs/tts/SPEECH_OPTIMIZER_V1.md` | ✅ |
| TTS_VOICE_GENERATION_V2 | `docs/tts/TTS_VOICE_GENERATION_V2.md` | ✅ |
| ASS_SUBTITLE_ENGINE_V1 | `docs/video/ASS_SUBTITLE_ENGINE_V1.md` | ✅ |
| SUBTITLE_INTELLIGENCE_ENGINE_V1 | `docs/video/SUBTITLE_INTELLIGENCE_ENGINE_V1.md` | ✅ |
| CINEMATIC_MOTION_ENGINE_V1 | `docs/video/CINEMATIC_MOTION_ENGINE_V1.md` | ✅ |
| ASSET_SCENE_SYSTEM_V1 | `docs/video/ASSET_SCENE_SYSTEM_V1.md` | ✅ |
| VIDEO_QUALITY_REVIEW_ENGINE_V1 | `docs/video-quality-review/VIDEO_QUALITY_REVIEW_ENGINE_V1.md` | ✅ |
| VIDEO_VALIDATION_RULES_V1 | `docs/video-quality-review/VIDEO_VALIDATION_RULES_V1.md` | ✅ |
| ROOT_CAUSE_ANALYSIS_ENGINE_V1 | `docs/video-quality-review/ROOT_CAUSE_ANALYSIS_ENGINE_V1.md` | ✅ |
| QUALITY_SCORING_ENGINE_V1 | `docs/video-quality-review/QUALITY_SCORING_ENGINE_V1.md` | ✅ |
| ENGINE_FEEDBACK_LOOP_V1 | `docs/video-quality-review/ENGINE_FEEDBACK_LOOP_V1.md` | ✅ |
| VIDEO_REVIEW_DEBUG_MODE_V1 | `docs/video-quality-review/VIDEO_REVIEW_DEBUG_MODE_V1.md` | ✅ |
| AUTO_REMEDIATION_ENGINE_V1 | `docs/video-quality-review/AUTO_REMEDIATION_ENGINE_V1.md` | ✅ |
| PUBLISHING_AND_GROWTH_ENGINE_V1 | `docs/publishing/PUBLISHING_AND_GROWTH_ENGINE_V1.md` | ✅ |

**Cultural Authenticity** (2026-07-06): implemented as prompt engineering only in
`agents/prompts/scene_planner.py` — no separate spec file. Adds cultural context
identification as the first step in per-scene reasoning, gates all subsequent decisions.

---

## 17. Test Suite

**Current count:** 1317 passed, 0 failed (as of 2026-07-06).

**Key test files:**
- `tests/test_human_quality_validation.py` — 47 tests for human_detector + HumanValidator
- `tests/test_image_prompt_engine.py` — prompt engine + enrich + review_prompt
- `tests/test_project_repository.py` — project storage
- `tests/test_bgm.py` — BGM pipeline integration
- `tests/test_video_encoding_optimization.py` — FFmpeg encoding params

**Files at repo root** (require live API keys, excluded from `tests/` run):
`test_gemini_image.py`, `test_hf_image.py`

---

## 18. Domain Models

`src/ytfactory/domain/` — pure dataclasses/Pydantic models (no I/O):
- `Project` — project metadata + stage status dict
  - stages: `research, script, scenes, images, audio, subtitles, video, publish`
  - status values: `pending | running | completed`
- `LLMResponse`, `SearchResult` — shared value objects
- `ImageRequest` — passed to image providers
- `scene.py` — scene dict schema helpers

`ProjectRepository` (`storage/project_repository.py`) — serializes `Project` to
`project.json`, tracks stage status.

---

## 19. Shared Constants

```python
# shared/constants.py
WORKSPACE_DIR = "workspace/jobs"
PROJECT_FILE = "project.json"
```

All pipelines resolve paths relative to CWD — run commands from repository root.

---

## 20. Boot Instructions for New Claude Sessions

1. Read this file (`docs/context/MASTER_CONTEXT_V2.md`) first.
2. Read `CLAUDE.md` for commands and the CLAUDE.md-specific architecture notes.
3. Check memory files in `/home/santosh/.claude/projects/.../memory/MEMORY.md`
   for session-specific feedback and project state.
4. Before implementing any new V1 specification: read the spec, propose an
   architecture review + integration plan, and get user approval before coding.
   **Never regress existing V1s.**
5. After any code change: run `uv run ruff check src/ && uv run ruff format src/`
   then `uv run pytest tests/ -q` and confirm 0 failures.
6. When patching `WORKSPACE_DIR` in tests: patch in the consuming module
   (`ytfactory.review.engine.WORKSPACE_DIR`), not in `shared.constants`.
7. The `.env` policy: comment out old value, add new value on the next line.
