# MASTER_CONTEXT_V3.md

# YouTube Factory — Master Project Context (V3)

> **Purpose:** Canonical project memory for YouTube Factory. Any new Claude Code session
> should read this document before reading feature-specific specifications.
> This supersedes `MASTER_CONTEXT_V2.md` and `MASTER_CONTEXT_V1.md`.
>
> **Last updated:** 2026-07-06
> **Test count:** 1506 passing, 0 failing

---

## 1. Project Vision

Build a production-grade AI-powered pipeline that automatically generates premium
documentary/spiritual YouTube videos with minimal manual effort.

**Core principles:**
- Documentary-quality storytelling and cinematic visuals
- Natural narration with contemplative pacing
- Professional subtitles (ASS format) with typography intelligence
- Cultural and historical authenticity in every visual
- Clothing & cultural authenticity enforced at both LLM and post-processing level
- Human subject quality enforcement at both generation and review time
- Modular, provider-agnostic architecture — each component is swappable
- Self-healing: quality gate → root cause → auto-remediation loop
- Incremental builds: SHA-256 manifest, skip unchanged stages, locked scene protection

---

## 2. Repository Layout

```
youtube-factory/
├── src/ytfactory/          # all production code (installed as `ytfactory` package)
├── tests/                  # pytest suite — run from repo root
├── workspace/jobs/         # gitignored runtime data (one dir per project)
├── workspace/music/        # BGM library: <category>/*.mp3
├── docs/                   # specs and context documents
│   ├── context/            # this file + V1/V2 + sprint context
│   ├── image-prompt-generation/
│   ├── video-quality-review/
│   ├── manual/             # V1 spec documents (e.g. INCREMENTAL_RENDERING_AND_SCENE_WORKSPACE_V1.md)
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
uv sync                                            # install dependencies
uv run ytfactory --help                            # CLI help
uv run ruff check src/ && uv run ruff format src/  # lint + format
uv run mypy src/                                   # type checking
uv run pytest tests/                               # all tests (1506 passing as of 2026-07-06)
uv run pytest tests/test_project_repository.py    # single file
uv run pytest -k "test_create"                     # filter by name
```

---

## 4. Two Execution Paths

### 4.1 Agentic Pipeline — `ytfactory run <topic>`

LangGraph graph in `src/ytfactory/agents/`. Nodes:
`research → script_writer → script_enhancer → scene_planner → scene_assets
→ video_renderer → video_concatenator → quality_review → human_review → remediation → publish`

State: `VideoState` in `agents/state.py`. Entry: `run_pipeline()` in `agents/runner.py`.

**Incremental routing:** When `--resume` or any `--force-*` is passed with `--project`, `run_pipeline()` routes to `_run_incremental()` which calls `BuildPipeline.run_incremental()`. The LangGraph graph is NOT re-run — only the linear pipeline stages execute selectively.

### 4.2 Sequential Pipeline — `ytfactory build <id>`

`BuildPipeline` in `src/ytfactory/build/pipeline.py`. Calls each pipeline class in order.
Two modes: `run()` (full rebuild) and `run_incremental()` (SHA-256 change detection, skips clean stages).

### 4.3 Internal Pipeline Chain (what `build` does in full mode)

```
ScenePipeline
→ ImagePipeline (with human quality retry + clothing policy)
→ VoicePipeline (TTS + pacing)
→ CaptionPipeline (ASS subtitles)
→ VideoPipeline (FFmpeg render + BGM mix)
→ ReviewPipeline (7-layer quality gate)
→ [AutoRemediationEngine if FAIL]
→ PublishPipeline (YouTube package)
```

---

## 5. CLI Reference (Key Commands)

### Full pipeline
```bash
ytfactory run "Topic" --auto                        # full agentic pipeline
ytfactory run "Topic" --script path.md --auto       # skip research, use own script
ytfactory build <id>                                # sequential pipeline
```

### Incremental / resume
```bash
ytfactory build <id> --resume                       # skip unchanged stages
ytfactory build <id> --force-images                 # force images + downstream
ytfactory build <id> --force-narration              # force voice + downstream
ytfactory build <id> --force-subtitles              # force captions + downstream
ytfactory build <id> --force-video                  # force video re-render + downstream
ytfactory build <id> --force-bgm                    # force BGM re-mix
ytfactory build <id> --force-publish                # force publish only
ytfactory build <id> --force-scene 8                # force all assets for scene 8
ytfactory build <id> --scene 3 --force-video        # force video for scene 3 only
ytfactory build <id> --resume --debug-incremental   # show ✓ reused / ⚠ rebuilt table

ytfactory run "Topic" --project <id> --resume       # incremental via agentic runner
ytfactory run "Topic" --project <id> --force-images
```

### Scene approval workflow
```bash
ytfactory scene list <id>                           # show all scene states
ytfactory scene approve <id> 3                      # approve scene 3
ytfactory scene reject <id> 8 --notes "too dark"    # mark Needs Revision
ytfactory scene lock <id> 5                         # lock (never auto-regenerated)
ytfactory scene unlock <id> 5                       # back to Approved
ytfactory scene review <id>                         # write review/scene-review.md
```

### Manual image replacement → incremental rebuild
```bash
cp better.png workspace/jobs/<id>/images/scene-008.png
ytfactory build <id> --resume
# Auto-detects checksum change → rebuilds motion + scene video + final + review + publish
```

### Stage-by-stage
```bash
ytfactory create "Title"         ytfactory research <id>
ytfactory import-script <id> path.md    ytfactory plan-scenes <id>
ytfactory generate-images <id>          ytfactory generate-voice <id>
ytfactory generate-captions <id>        ytfactory render <id>
ytfactory review <id>                   ytfactory remediate <id>
ytfactory publish <id>
ytfactory doctor                         # check API keys + FFmpeg
```

Full CLI reference: `docs/CLI_REFERENCE.md`

---

## 6. Workspace Layout

```
workspace/jobs/<project-id>/
├── project.json              # Project metadata + stage statuses
├── .pipeline-manifest.json   # SHA-256 checksums for incremental builds
├── research/                 # research.md, research.json, sources.json
├── script/                   # script.md (imported or LLM-enhanced)
├── scenes/
│   ├── scene-plan.json       # ← CENTRAL ARTIFACT: all downstream reads this
│   └── scene-status.json     # per-scene approval states (SceneWorkspace)
├── images/                   # scene-001.png … + manifest.json + debug/
├── audio/                    # scene-001.mp3 + scene-001.timing.json …
├── subtitles/                # scene-001.srt / scene-001.ass …
├── video/                    # scene-001.mp4 … + final.mp4
├── review/                   # 17 quality gate output files (see §9)
│   └── scene-review.md       # per-scene status report (ytfactory scene review)
├── remediation/              # 4 remediation output files
└── publish/                  # complete YouTube upload package (8 files)
```

`scene-plan.json` is the **central artifact**: every downstream stage reads
`scenes[].visual_prompt`, `scenes[].narration`, and `scenes[].duration_seconds`.

---

## 7. Configuration (Settings)

`Settings` (`config/settings.py`) — Pydantic `BaseSettings` loaded from `.env`.

**.env policy:** when changing a value, comment out the old line and put the new value on the next line — never overwrite in place.

```
# API Keys
GEMINI_API_KEY, TAVILY_API_KEY, HF_TOKEN, GROQ_API_KEY, ANTHROPIC_API_KEY

# Providers (defaults)
LLM_PROVIDER=gemini         IMAGE_PROVIDER=pollinations
TTS_PROVIDER=edge            SEARCH_PROVIDER=tavily

# Models
GEMINI_TEXT_MODEL=gemini-2.5-flash
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
HF_IMAGE_MODEL=black-forest-labs/FLUX.1-schnell

# Image / Video
IMAGE_WIDTH=1920  IMAGE_HEIGHT=1080
VIDEO_WIDTH=1920  VIDEO_HEIGHT=1080  VIDEO_FPS=30
RENDER_PROFILE=balanced     # draft | balanced | cinematic | premium

# Human Quality
IMAGE_HUMAN_MAX_RETRIES=2
IMAGE_HUMAN_MIN_SHARPNESS=12.0

# TTS / Pacing
TTS_PACING_ENABLED=true
TTS_PACING_PROFILE=spiritual   # normal|documentary|spiritual|meditation|slow_reflection
TTS_MAX_RETRIES=3

# BGM (opt-in)
BGM_ENABLED=false
BGM_CATEGORY=auto
BGM_LIBRARY_PATH=workspace/music
BGM_VOLUME=0.20

# Subtitles
SUBTITLE_FORMAT=ass
SUBTITLE_ASS_THEME=default     # default|minimal|high_contrast|cinematic

# Video encoding
VIDEO_CRF=23  VIDEO_PRESET=medium
VIDEO_INTRO_ENABLED=true  VIDEO_INTRO_SECONDS=1.5
```

---

## 8. Image Pipeline — Full Stack

### 8.1 Layers in `enrich_for_provider(scenes, provider)`

Applied in order after the LLM generates `visual_prompt` for each scene:

1. **Human quality reinforcement** (`human_detector.py`) — appends 7 quality markers
2. **Subject Dominance Rule** — appends prominence hint for wide shots with humans
3. **Clothing & Cultural Authenticity Policy** (`clothing_policy.py`) — see §8.3
4. **Provider anatomy reinforcement or negative prompt**
   - Providers with negative prompt support (`huggingface`, `a1111`, `automatic1111`, `sd-webui`): set `scene["negative_prompt"]` including clothing terms
   - Others (pollinations, gemini): append `_ANATOMY_REINFORCEMENT` to positive prompt

`review_prompt()` then validates every prompt for openers, clichés, style markers, clothing violations, and word count.

### 8.2 Human Quality Validation V1

File: `src/ytfactory/images/human_detector.py`

**`_HUMAN_INDICATORS`** (whole-word `\b` matched):
man, woman, person, people, child, children, boy, girl, elder, baby,
monk, warrior, farmer, leader, soldier, scholar, ruler, priest, guru, sage, philosopher,
king, queen, emperor, mother, father, villager, peasant, merchant, artisan, face, portrait, crowd, audience

**⚠ "human" is NOT in `_HUMAN_INDICATORS`** — it appears in "natural human anatomy" (anatomy reinforcement phrase) which would cause false detection on the second pass.

**Key functions:**
```python
detect_human_presence(prompt) -> bool      # whole-word regex on 44 indicators
add_human_quality_reinforcement(prompt)    # idempotent, appends 7 quality phrases
apply_subject_dominance_rule(prompt, shot_type)  # wide shots only, idempotent
compute_sharpness(image_path) -> float     # Pillow FIND_EDGES stddev, 0.0 on error
```

**Sharpness thresholds:**
- Pipeline retry: `image_human_min_sharpness = 12.0` (aggressive, up to 2 retries)
- HUM_003 validator: `8.0` (catches only genuinely blurry outputs)

### 8.3 Clothing & Cultural Authenticity Policy

File: `src/ytfactory/images/clothing_policy.py`

**Enforced at two levels:**
1. **LLM pre-generation** — `agents/prompts/scene_planner.py` includes a full CLOTHING & CULTURAL AUTHENTICITY section instructing the LLM to: specify clothing for every human scene, infer from context (office/temple/ashram/home/etc.), never describe bare torso or nudity unless authentic exception
2. **Post-generation enforcement** — `apply_clothing_policy()` called in `enrich_for_provider()` for every scene

**`detect_violation(prompt)`** — detects 18 violation terms:
`nude, naked, nudity, unclothed, undressed, no clothing, no clothes, no shirt, shirtless, bare-chested, bare chested, bare chest, bare torso, bare upper body, topless, skimpy, revealing clothing, provocative clothing` etc.

**`is_authentic_exception(prompt)`** — True for: sadhu, Naga sadhus, Hindu monk, jain monk, Digambara, Buddhist/Zen/Theravada monk, ancient ascetic, vedic ascetic, yogi, ancient yogi, indigenous traditional

**Decision tree in `apply_clothing_policy(prompt, scene)`:**
1. No human → pass through unchanged
2. Violation + authentic exception → append respectful framing (`"cultural dignity, no sexualization, no exaggerated musculature"`)
3. Violation + no exception → append enforcement (`"wearing [context-inferred clothing], no bare torso, no nudity"`)
4. Human, no violation, no clothing mentioned → append inferred clothing hint

**`infer_clothing(scene)`** — infers appropriate clothing from scene narration/title:
- office → professional attire; temple/mandir → modest traditional; ashram/vedic → dhoti and angavastram; home → casual t-shirt/jeans; park → casual outdoor; Buddhist → grey/saffron robes; etc.

**`get_negative_clothing_terms()`** — added to `_DEFAULT_NEGATIVE_PROMPT` for providers that support negative prompts.

**⚠ Important:** Authentic exception subjects (sadhu, yogi, ascetic) are NOT in `_HUMAN_INDICATORS`. `apply_clothing_policy` uses `is_authentic_exception(prompt)` as a secondary human-presence check so these subjects are still processed by the policy.

---

## 9. Review Layer — 7-Layer Quality Gate

Entry: `VideoQualityReviewEngine.review()` in `review/engine.py`

### Layer 1 — Stage checks (`review/stages/`)
`AssetIntegrityStage`, `TimelineStage`, `ContentStage`, `ProductionQualityStage`

### Layer 2 — Validation Rules (`review/validation/`) — 9 validators

| # | Validator | Key rules |
|---|---|---|
| 1 | ScriptValidator | word count, filler %, sentence density |
| 2 | NarrationValidator | words/min pace, silence gaps |
| 3 | SubtitleValidator | CPS ≤18, line count ≤2, timing sync |
| 4 | ImageValidator | file exists, resolution, format |
| 5 | HumanValidator | HUM_001 (quality markers), HUM_002 (dominance), HUM_003 (sharpness ≥8) |
| 6 | MotionValidator | motion type presence, profile match |
| 7 | AudioValidator | file presence, duration match, volume |
| 8 | RenderingValidator | black frames, encoding params, file size |
| 9 | StoryValidator | narrative arc, hook, closing |

### Layer 3 — Root Cause Analysis (`review/rca/`)
Groups failures by engine, builds remediation chains, detects cross-scene patterns.

### Layer 4 — Quality Scoring (`review/scoring/`)
Weighted average across 8 categories → 0–100 score, letter grade (A+→F), PASS (≥70) / FAIL.

**Category weights:**
rendering 0.20 | narration 0.15 | image 0.15 | audio 0.15 | subtitle 0.10 | script 0.10 | motion 0.10 | storytelling 0.05

### Layer 5 — Engine Feedback Loop (`review/efl/`)
12 canonical engine targets. Recurring issues (≥2 occurrences) get priority escalated.
Cross-run accumulation in `recurring-patterns.json`.

### Layer 6 — Debug Mode (`review/debug/`)
`DebugLevel.OFF|BASIC|DETAILED|VERBOSE`. Zero overhead when OFF (the default).

### Layer 7 — Auto Remediation (`review/remediation/`)
plan → execute → re-validate loop (up to `max_retries=3`, stops when score ≥ 70).
6 strategies: retry_validation, regenerate_subtitles, regenerate_audio, regenerate_image, regenerate_video_clip, full_regeneration.

### Review output files (17 files in `review/`)
review-report.md, scene-review.json, review-debug.json, validation-report.json,
root-cause-report.md, root-cause.json, engine-owner-summary.json, recurring-issues.json,
quality-score.json, quality-report.md, score-breakdown.json, score-history.json,
engine-feedback.json, engine-feedback.md, engine-priority-report.json,
recurring-patterns.json, improvement-roadmap.md
+ `debug/` (7 files, when debug level ≠ OFF)

---

## 10. Incremental Rendering & Scene Workspace V1

### 10.1 Architecture

`src/ytfactory/incremental/` — core engine:

| File | Purpose |
|---|---|
| `models.py` | `SceneState` enum, `ManifestEntry`, `ChangeReport` |
| `manifest.py` | `PipelineManifest` — SHA-256 checksums → `.pipeline-manifest.json` |
| `deps.py` | Dependency graph, output patterns, force-flag mapping, `downstream_stages()` |
| `change_detector.py` | `ChangeDetector` — glob scan vs. manifest, scene-scoped filtering |
| `scene_workspace.py` | `SceneWorkspace` — per-scene state machine → `scenes/scene-status.json` |
| `reporter.py` | `IncrementalReporter` — console table, writes `review/scene-review.md` |
| `engine.py` | `IncrementalBuildEngine` — main orchestrator |

`src/ytfactory/scene/cli.py` — `scene_app` Typer subapp (list, approve, reject, lock, unlock, review)

### 10.2 Scene States

```
Draft → Needs Review → Approved → Locked
              ↓
         Needs Revision  (quality failure or manual reject)
```

**Locked** = NEVER auto-regenerated by any `--resume` or `--force-*` run.
Only `ytfactory scene unlock <id> N` or `--force-scene N` (bypasses lock for one scene) can override.

### 10.3 How Incremental Works

1. `IncrementalBuildEngine.analyze(force_stages, scene_filter)` — scans all stage output patterns against stored SHA-256 checksums
2. Changed / new / missing files → mark their stage as invalidated
3. `downstream_stages()` propagates invalidation transitively
4. `BuildPipeline.run_incremental()` — for each stage in order: `engine.needs_run(stage, report)` → skip or run → `engine.record_stage_outputs(stage)`
5. Console output: `✓ Images reused` / `⚠ Video rebuilt`

### 10.4 Scene Workspace Workflow

The approval workflow is **entirely manual and post-run** — the pipeline never pauses mid-run.

```bash
ytfactory build <id>          # run pipeline; scenes start as Draft
ytfactory scene list <id>     # see what needs review
ytfactory scene approve <id> 3  ytfactory scene lock <id> 3    # lock approved scenes
ytfactory build <id> --resume # future runs skip locked scenes
```

---

## 11. Cinematic Motion & Video Rendering

### 11.1 Continuous Renderer (FFmpeg)

`video/ffmpeg.py` `render_continuous()` — single-pass filter_complex encode.
All scenes in one H.264 stream, no GOP boundaries.
**Fixes:** YouTube transcoder pause issue caused by stream-copy concat (`-c copy`).

**Critical fix — zoompan duration bug:**
`trim=duration={dur:.4f},setpts=PTS-STARTPTS` is applied BEFORE subtitle burn-in.

Without this: zoompan fed a video stream (created by `-loop 1 -framerate fps -t dur`)
outputs `d` frames PER input frame → total output = `dur² × fps` seconds (e.g. 39 min instead of 5 min).
With trim: filter-graph backpressure stops zoompan after exactly `d` total frames → correct duration.

Placement before subtitles: subtitle burn-in only processes frames that survive the trim — no wasted computation.

### 11.2 Cinematic Motion Engine (`cinematic/`)

4 render profiles: `draft` (static) | `balanced` (simple zoom/pan) | `cinematic` (emotion-aware, 8 motion types) | `premium` (wider range, film grain)

### 11.3 Per-Scene Videos → Final

`VideoPipeline.run()`: per-scene H.264 clips → `render_continuous()` → single-pass final.mp4 → BGM mix (if enabled).

---

## 12. TTS & Voice Pipeline

`VoicePipeline` → SpeechOptimizer → SpeechFormatter → EmotionEngine → ContemplativePacingEngine → Edge TTS / ElevenLabs.

**Pacing profiles:** `normal | documentary | spiritual | meditation | slow_reflection`
`spiritual`: 500–700 ms normal pause, 1.2–1.8 s important, 2.0–2.5 s major-realization.

Output: `audio/scene-NNN.mp3` + `scene-NNN.timing.json` (word/sentence timestamps, used by ChaptersGenerator).

---

## 13. ASS Subtitle Engine

`subtitles/` — professional ASS subtitles.
Key: `engine.py`, `segmenter.py`, `timing.py`, `ass/writer.py`, `ass/theme_manager.py`.
Standards: ≤18 CPS, ≤42 chars/line, ≤2 lines/cue (Netflix/BBC).
Output: `scene-NNN.ass` (primary) + `scene-NNN.srt` (compatibility).

---

## 14. BGM System (`bgm/`)

Opt-in (`BGM_ENABLED=false`). Components: detector, library, mixer, pipeline.
Ducking sidechain (threshold=0.02, ratio=4.0) automatically drops BGM under narration.
Library: `workspace/music/<category>/*.mp3`.

---

## 15. Scene Planning — Cultural & Visual Intelligence

Entry: `ScenePipeline` → LLM using `_VISUAL_PROMPTS_TEMPLATE` in `agents/prompts/scene_planner.py`.

**LLM prompt sections (in order):**

1. **BANNED patterns** — opening phrase ban, camera-as-subject ban, narration-copy ban, generic environment ban, AI visual cliché ban, anatomy safety
2. **CULTURAL MIXING ban** — all elements must belong to one cultural world
3. **CLOTHING & CULTURAL AUTHENTICITY** (added 2026-07-06) — mandatory clothing for every human scene; context → clothing table (office/temple/ashram/home/park/Buddhist/medieval etc.); authentic exceptions list; never bare torso unless sadhu/jain monk/ancient ascetic
4. **HUMAN SUBJECT QUALITY** — 7 mandatory quality markers for human subjects; Subject Dominance Rule for wide shots
5. **CULTURAL AUTHENTICITY** — identify one cultural context, apply throughout; 8 cultural context → visual elements mappings
6. **CHARACTER BIBLE** — one physical description locked across all scenes
7. **STORYBOARD** — 6-step pre-writing plan (arc, roles, hero frame, diversity, metaphors)
8. **PER-SCENE INTERNAL REASONING (A–J):**
   - **A: Cultural context + Clothing check** — identify era/culture; confirm environment, clothing, objects match; clothing check: what are they wearing? never bare torso unless authentic exception
   - B–J: core meaning, emotion, metaphor, subject, environment, shot type, lighting, palette, self-critique
9. **PROMPT STRUCTURE** — 10-element flowing paragraph
10. **VISUAL CONTINUITY** — protagonist consistency, gradual color temperature arc
11. **WRITING RULES** — 60–90 words, no "A person" opener, weave shot/lighting naturally

---

## 16. Publishing Layer (`publish/`)

`PublishPipeline.run(project_id)` writes complete YouTube package to `publish/`:
ChaptersGenerator, TitleGenerator, SEOGenerator, DescriptionGenerator, ThumbnailGenerator (1280×720), UploadPackageGenerator.

`ChaptersGenerator` reads real audio duration from `timing.json` last entry's `"end"` field.

---

## 16.5 Brand Template System V1

**Spec:** `docs/branding/BRAND_TEMPLATE_SYSTEM_V1.md`
**Single source of truth:** `config/brand_config.yaml` (repo root)
**Module:** `src/ytfactory/branding/` (`config.py`, `validator.py`, `__init__.py`)

### YAML structure (6 sections)
`channel_name` | `opening` | `closing` | `cta` | `signature` | `voice` | `branding`

### Required script structure (enforced by LLM prompts + `BrandValidator`)
```
Hook → Channel Welcome (opening.text) → Teaching → Reflection
     → Brand Signature (closing.text) → CTA (cta.text) → Closing Quote (signature.text)
```

### Key design points
- **`get_brand_config()`** — singleton with lazy load; `reset_brand_config_cache()` for test isolation
- **`ContentSection.text()`** — joins multiline YAML template into clean single-line string
- **`_CLOSING_TRIGGERS`** (scene_planner) — frozenset computed at import time; supplemented by dynamic `get_brand_config()` call in `_is_closing_scene()` to handle runtime reloads (multi-channel)
- **Backward compatibility** — falls back to Atma Theory defaults if `config/brand_config.yaml` absent
- **Multi-channel** — swap `config/brand_config.yaml` only; zero code changes for a new channel
- **No "Atma Theory" in production code** — only in `branding/config.py` default constants and `config/brand_config.yaml`
- **`branding.py` public API:** `get_welcome()`, `get_closing()`, `get_closing_brand()`, `get_cta()`, `get_transition()`
- **`BrandValidator`** — 6 checks: hook exists, opening in first 30%, closing+brand in last 45%, CTA once, brand assertion before CTA, closing quote after CTA

### Wiring
- `agents/prompts/script_writer.py` — `build_write_script_prompt` has 10-step structure with `closing_brand`
- `agents/prompts/script_enhancer.py` — `_ENHANCER_TEMPLATE` CHANNEL FRAME includes all 4 brand elements
- `agents/nodes/script_writer.py` — imports `get_closing_brand`, passes to prompt builder
- `agents/nodes/script_enhancer.py` — imports `get_closing_brand`, passes to prompt builder
- `agents/nodes/scene_planner.py` — reads `asset_path` and `asset_animation` from brand config

---

## 17. Provider System

Business logic never imports concrete providers — calls factory functions:

| Type | Base | Implementations | Setting |
|---|---|---|---|
| LLM | `providers/llm/base.py` | Gemini, Groq, OpenAI, Ollama, Anthropic | `LLM_PROVIDER` |
| Search | `providers/search/base.py` | Tavily | `SEARCH_PROVIDER` |
| Image | `providers/image/base.py` | HuggingFace, Gemini, Pollinations, A1111, Mock | `IMAGE_PROVIDER` |
| TTS | `providers/tts/base.py` | Edge TTS, ElevenLabs | `TTS_PROVIDER` |

**Negative prompt split:** `{"huggingface", "a1111", "automatic1111", "sd-webui"}` support native negative_prompt API; others (pollinations, gemini) get anatomy + clothing reinforcement appended to positive prompt.

---

## 18. Implemented V1 Specifications

| Spec | Status |
|---|---|
| IMAGE_PROMPT_ENGINE_V4 | ✅ |
| HUMAN_QUALITY_AND_SUBJECT_VALIDATION_V1 | ✅ |
| SCRIPT_GENERATION_RULES_V1 | ✅ |
| SCRIPT_BRANDING_V1 | ✅ |
| SCRIPT_PACING_AND_DURATION_RULES_V2 | ✅ |
| SPEECH_OPTIMIZER_V1 | ✅ |
| TTS_VOICE_GENERATION_V2 | ✅ |
| ASS_SUBTITLE_ENGINE_V1 | ✅ |
| SUBTITLE_INTELLIGENCE_ENGINE_V1 | ✅ |
| CINEMATIC_MOTION_ENGINE_V1 | ✅ |
| ASSET_SCENE_SYSTEM_V1 | ✅ |
| VIDEO_QUALITY_REVIEW_ENGINE_V1 | ✅ |
| VIDEO_VALIDATION_RULES_V1 | ✅ |
| ROOT_CAUSE_ANALYSIS_ENGINE_V1 | ✅ |
| QUALITY_SCORING_ENGINE_V1 | ✅ |
| ENGINE_FEEDBACK_LOOP_V1 | ✅ |
| VIDEO_REVIEW_DEBUG_MODE_V1 | ✅ |
| AUTO_REMEDIATION_ENGINE_V1 | ✅ |
| PUBLISHING_AND_GROWTH_ENGINE_V1 | ✅ |
| INCREMENTAL_RENDERING_AND_SCENE_WORKSPACE_V1 | ✅ |
| BRAND_TEMPLATE_SYSTEM_V1 | ✅ |
| Clothing & Cultural Authenticity Policy | ✅ (no separate spec; implemented in `clothing_policy.py` + scene_planner prompt) |

---

## 19. Test Suite

**Current count:** 1506 passed, 0 failed (as of 2026-07-06).

Key test files:
- `tests/test_incremental.py` — 53 tests: manifest, change detector, scene workspace, engine, reporter
- `tests/test_clothing_policy.py` — 53 tests: detect_violation, is_authentic_exception, apply_clothing_policy, infer_clothing, diagnostics integration, review_prompt integration
- `tests/test_human_quality_validation.py` — 47 tests: human_detector + HumanValidator
- `tests/test_image_prompt_engine.py` — prompt engine + enrich + review_prompt
- `tests/test_video_pipeline_duration.py` — audio duration resolution
- `tests/test_bgm.py`, `tests/test_video_encoding_optimization.py`

Files at repo root (require live API keys, excluded from `tests/` run):
`test_gemini_image.py`, `test_hf_image.py`

---

## 20. Domain Models

`src/ytfactory/domain/` — pure dataclasses/Pydantic (no I/O):
- `Project` — metadata + stage status (`pending|running|completed`)
- `LLMResponse`, `SearchResult`, `ImageRequest`

`ProjectRepository` (`storage/project_repository.py`) — serializes `Project` to `project.json`.

```python
# shared/constants.py
WORKSPACE_DIR = "workspace/jobs"
PROJECT_FILE = "project.json"
```

All pipelines resolve paths relative to CWD — run commands from repo root.

---

## 21. Test Patterns

```python
# Patching WORKSPACE_DIR — always patch in the consuming module, NOT in shared.constants
monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))
monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
```

---

## 22. Known Design Decisions & Gotchas

| Decision | Reason |
|---|---|
| "human" excluded from `_HUMAN_INDICATORS` | Anatomy phrase "natural human anatomy" contains "human" → false detection on second pass |
| Sadhu/yogi/ascetic not in `_HUMAN_INDICATORS` | `apply_clothing_policy` handles them via `is_authentic_exception()` |
| Clothing policy runs AFTER human quality reinforcement | Human markers must be in the prompt before clothing enforcement is evaluated |
| `trim=duration={dur:.4f}` before subtitles in `render_continuous` | Zoompan fed a video stream outputs d frames PER input frame → `dur² × fps` seconds without trim |
| `_DEFAULT_NEGATIVE_PROMPT` includes clothing terms | Negative prompt is built at module load time via `get_negative_clothing_terms()` |
| `ytfactory run --resume` routes to `BuildPipeline.run_incremental`, NOT LangGraph | LangGraph graph has no mechanism for selective stage skipping |
| Locked scenes skipped silently (no error) | `needs_run()` returns False; locked guard is in `SceneWorkspace.mark_needs_revision()` |
| `scene-plan.json` is central — never delete it | Images, voice, captions, video all read from it; deleting it breaks all downstream |
| `.gitignore build/` matches `src/ytfactory/build/` | Use `git add -f src/ytfactory/build/` |

---

## 23. Boot Instructions for New Claude Sessions

1. Read `docs/context/MASTER_CONTEXT_V3.md` (this file) first.
2. Read `CLAUDE.md` for commands and architecture notes specific to Claude Code.
3. Check memory index at `/home/santosh/.claude/projects/-home-santosh-pvt-files-youtube-factory/memory/MEMORY.md`.
4. **Before implementing any new V1 spec:** read the spec, perform an architecture review, identify all interaction surfaces with existing V1s, and get user approval before writing production code. Never regress existing V1s.
5. After any code change: `uv run ruff check src/ && uv run ruff format src/` then `uv run pytest tests/ -q` — confirm 0 failures.
6. **Execute Mode by default** — do NOT enter Plan Mode or spawn multiple agents unless the user explicitly requests it.
7. **.env policy** — comment out old value, add new on next line, never overwrite.
