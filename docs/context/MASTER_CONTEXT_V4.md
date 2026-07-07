# MASTER_CONTEXT_V4.md

# YouTube Factory — Master Project Context (V4)

> **Purpose:** Canonical project memory for YouTube Factory. Any new Claude Code session
> should read this document before reading feature-specific specifications.
> This supersedes `MASTER_CONTEXT_V3.md`, `V2.md`, and `V1.md`.
>
> **Last updated:** 2026-07-06
> **Test count:** 1554 passing, 0 failing

---

## 1. Project Vision

Build a production-grade AI-powered pipeline that automatically generates premium
documentary/spiritual YouTube videos with minimal manual effort.

**Core principles:**
- Documentary-quality storytelling and cinematic visuals
- Natural narration with contemplative pacing
- Professional subtitles (ASS format) with LLM-driven typography intelligence
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
│   ├── context/            # this file + V1/V2/V3 context
│   ├── image-prompt-generation/
│   ├── video-quality-review/
│   ├── manual/             # V1 spec documents
│   ├── video/              # subtitle + cinematic specs
│   ├── tts/
│   ├── script/
│   └── branding/
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
uv run pytest tests/                               # all tests (1554 passing)
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

### 4.3 Internal Pipeline Chain (full build mode)

```
ScenePipeline
→ ImagePipeline (human quality retry + clothing policy)
→ VoicePipeline (TTS + contemplative pacing)
→ CaptionPipeline (ASS subtitles + optional LLM editing pass)
→ VideoPipeline (FFmpeg continuous render + BGM mix)
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
```

### Scene approval workflow
```bash
ytfactory scene list <id>
ytfactory scene approve <id> 3
ytfactory scene reject <id> 8 --notes "too dark"
ytfactory scene lock <id> 5
ytfactory scene unlock <id> 5
ytfactory scene review <id>
```

### Stage-by-stage
```bash
ytfactory create "Title"           ytfactory research <id>
ytfactory import-script <id> path  ytfactory plan-scenes <id>
ytfactory generate-images <id>     ytfactory generate-voice <id>
ytfactory generate-captions <id>   ytfactory render <id>
ytfactory review <id>              ytfactory remediate <id>
ytfactory publish <id>
ytfactory doctor                    # check API keys + FFmpeg
```

Full CLI reference: `docs/CLI_REFERENCE.md`

---

## 6. Workspace Layout

```
workspace/jobs/<project-id>/
├── project.json                 # metadata + stage statuses
├── .pipeline-manifest.json      # SHA-256 checksums for incremental builds
├── research/
├── script/
├── scenes/
│   ├── scene-plan.json          # ← CENTRAL ARTIFACT: all downstream reads this
│   └── scene-status.json        # per-scene approval states (SceneWorkspace)
├── images/                      # scene-001.png … + manifest.json + debug/
├── audio/                       # scene-001.mp3 + scene-001.timing.json …
├── subtitles/                   # scene-001.srt / scene-001.ass …
├── subtitle-debug/              # SubtitleEngine + editor debug files
│   └── editor/                  # {scene-id}-original.srt/edited.srt/diff.md
├── video/                       # scene-001.mp4 … + final.mp4
├── review/                      # 17 quality gate files (see §9)
│   └── scene-review.md
├── remediation/                 # 4 remediation files
└── publish/                     # complete YouTube upload package
```

`scene-plan.json` is the **central artifact**: every downstream stage reads
`scenes[].visual_prompt`, `scenes[].narration`, and `scenes[].duration_seconds`.

---

## 7. Configuration (Settings)

`Settings` (`config/settings.py`) — Pydantic `BaseSettings` loaded from `.env`.

**.env policy:** comment out old value, add new value on next line — never overwrite.

```
# API Keys
GEMINI_API_KEY, TAVILY_API_KEY, HF_TOKEN, GROQ_API_KEY, ANTHROPIC_API_KEY

# Providers
LLM_PROVIDER=anthropic      IMAGE_PROVIDER=huggingface
TTS_PROVIDER=edge           SEARCH_PROVIDER=tavily

# Models
GEMINI_TEXT_MODEL=gemini-2.5-flash
ANTHROPIC_MODEL=claude-haiku-4-5

# Image / Video
IMAGE_WIDTH=1280  IMAGE_HEIGHT=720
VIDEO_WIDTH=1920  VIDEO_HEIGHT=1080  VIDEO_FPS=30
RENDER_PROFILE=balanced   # draft|balanced|cinematic|premium

# Human Quality
IMAGE_HUMAN_MAX_RETRIES=2
IMAGE_HUMAN_MIN_SHARPNESS=12.0

# TTS / Pacing
TTS_PACING_ENABLED=true
TTS_PACING_PROFILE=spiritual

# BGM (opt-in)
BGM_ENABLED=true
BGM_VOLUME=0.35
BGM_DUCK_FLOOR=0.05
BGM_DUCK_RATIO=2.5
BGM_DUCK_ATTACK_MS=50
BGM_DUCK_RELEASE_MS=600
BGM_FADE_IN_SECONDS=1.5
BGM_FADE_OUT_SECONDS=2.5

# Subtitles
SUBTITLE_FORMAT=ass
SUBTITLE_ASS_THEME=default

# Subtitle Editor (opt-in — off by default)
# SUBTITLE_EDITOR_ENABLED=true  → enable LLM editorial pass
# SUBTITLE_EDITOR_PROVIDER=llm  → "llm" or "mock"

# Video encoding
VIDEO_CRF=23  VIDEO_PRESET=medium
VIDEO_INTRO_ENABLED=true  VIDEO_INTRO_SECONDS=1.5
```

---

## 8. Image Pipeline — Full Stack

### 8.1 Layers in `enrich_for_provider(scenes, provider)`

Applied in order after the LLM generates `visual_prompt`:

1. **Human quality reinforcement** (`human_detector.py`) — appends 7 quality markers
2. **Subject Dominance Rule** — prominence hint for wide shots with humans
3. **Clothing & Cultural Authenticity Policy** (`clothing_policy.py`) — see §8.3
4. **Provider anatomy reinforcement or negative prompt**
   - HF/A1111/SD-WebUI: `scene["negative_prompt"]` with clothing terms
   - Others (pollinations, gemini): append `_ANATOMY_REINFORCEMENT` to positive prompt

### 8.2 Human Quality Validation V1

File: `src/ytfactory/images/human_detector.py`

**`_HUMAN_INDICATORS`** (44 terms, whole-word `\b` matched):
man, woman, person, people, child, children, boy, girl, elder, baby,
monk, warrior, farmer, leader, soldier, scholar, ruler, priest, guru, sage, philosopher,
king, queen, emperor, mother, father, villager, peasant, merchant, artisan, face, portrait, crowd, audience

**⚠ "human" is NOT in `_HUMAN_INDICATORS`** — it appears in "natural human anatomy" → false detection.

```python
detect_human_presence(prompt) -> bool       # whole-word regex
add_human_quality_reinforcement(prompt)     # idempotent, 7 markers
apply_subject_dominance_rule(prompt, shot)  # wide shots only, idempotent
compute_sharpness(image_path) -> float      # Pillow FIND_EDGES stddev
```

Sharpness: retry threshold = `12.0`, HUM_003 validator threshold = `8.0`.

### 8.3 Clothing & Cultural Authenticity Policy

File: `src/ytfactory/images/clothing_policy.py`

Enforced at two levels:
1. **LLM pre-generation** — `scene_planner.py` prompt: mandatory clothing per human scene
2. **Post-generation** — `apply_clothing_policy()` in `enrich_for_provider()`

`detect_violation(prompt)` — 18 bare/nudity terms.
`is_authentic_exception(prompt)` — sadhu, Naga, Hindu/Jain/Buddhist monk, ascetic, yogi, Digambara, indigenous traditional.

**Decision tree:** no human → pass through | violation + exception → append dignity framing | violation + no exception → append clothing enforcement | human + no clothing → append inferred clothing hint.

**⚠ Sadhu/yogi/ascetic not in `_HUMAN_INDICATORS`** — `apply_clothing_policy` handles them via `is_authentic_exception()`.

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
`DebugLevel.OFF|BASIC|DETAILED|VERBOSE`. Zero overhead when OFF (default).

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
| `manifest.py` | `PipelineManifest` — SHA-256 → `.pipeline-manifest.json` |
| `deps.py` | Dependency graph, force-flag mapping, `downstream_stages()` |
| `change_detector.py` | `ChangeDetector` — glob scan vs manifest |
| `scene_workspace.py` | `SceneWorkspace` — per-scene state machine → `scene-status.json` |
| `reporter.py` | `IncrementalReporter` — console table + `scene-review.md` |
| `engine.py` | `IncrementalBuildEngine` — main orchestrator |

`src/ytfactory/scene/cli.py` — `scene_app` Typer subapp.

### 10.2 Scene States

```
Draft → Needs Review → Approved → Locked
              ↓
         Needs Revision  (quality failure or manual reject)
```

**Locked** = NEVER auto-regenerated. Only `ytfactory scene unlock <id> N` or `--force-scene N` can override.

### 10.3 How Incremental Works

1. Scan all stage output patterns against stored SHA-256 checksums
2. Changed/new/missing files → mark stage as invalidated
3. `downstream_stages()` propagates invalidation transitively
4. `BuildPipeline.run_incremental()` — `engine.needs_run(stage, report)` → skip or run → record outputs
5. Console: `✓ Images reused` / `⚠ Video rebuilt`

---

## 11. Cinematic Motion & Video Rendering

### 11.1 Continuous Renderer (`video/ffmpeg.py`)

`render_continuous()` — single-pass filter_complex encode. All scenes in one H.264 stream, no GOP boundaries. Fixes YouTube transcoder pause issue caused by stream-copy concat.

**Critical zoompan fix:** `trim=duration={dur:.4f},setpts=PTS-STARTPTS` applied BEFORE subtitle burn-in. Without this, zoompan outputs `d² × fps` seconds (e.g. 39 min instead of 5 min) due to filter-graph backpressure.

### 11.2 Render Profiles

`draft` (static) | `balanced` (simple zoom/pan) | `cinematic` (emotion-aware, 8 motion types) | `premium` (wider range, film grain)

### 11.3 Final Video Assembly

`VideoPipeline.run()`: per-scene H.264 clips → `render_continuous()` → single final.mp4 → BGM mix (if enabled).

---

## 12. BGM System (`bgm/`) — Two-Path Filter Architecture

Opt-in (`BGM_ENABLED=false` default). Components: `config.py`, `detector.py`, `library.py`, `mixer.py`, `pipeline.py`.

**Two-path FFmpeg filter (`_build_filter()`):**

```
BGM → asplit → Path A: floor (always-on at duck_floor volume, fade-in/out)
             → Path B: main  (volume = bgm_volume - duck_floor) → sidechaincompress(narration) → fade-in/out
Path A + Path B → amix[bgm_ducked]
narration + bgm_ducked → amix → alimiter[audio_out]
```

During silence: floor + main_vol = bgm_volume (e.g. 35%).
During speech: floor + main_ducked ≈ duck_floor + small residual (e.g. 5–11%).

**Current defaults (all configurable via Settings + .env):**

| Setting | Default | Purpose |
|---|---|---|
| `bgm_volume` | 0.35 | Total volume during silence |
| `bgm_duck_floor` | 0.05 | Minimum BGM level during active speech |
| `bgm_duck_threshold` | 0.02 | ~−34 dBFS speech onset detection |
| `bgm_duck_ratio` | 2.5 | Gentle 2.5:1 compression ratio |
| `bgm_duck_attack_ms` | 50 | Fast onset (50 ms) |
| `bgm_duck_release_ms` | 600 | Snappy recovery (600 ms) |
| `bgm_fade_in_seconds` | 1.5 | Fade-in at video start |
| `bgm_fade_out_seconds` | 2.5 | Fade-out at video end |

Library: `workspace/music/<category>/*.mp3`. Category auto-detected from scene titles when `BGM_CATEGORY=auto`.

BGM is applied as part of `VideoPipeline._compose_final_video_continuous()` — NOT via `BGMPipeline.run()` (which exists for standalone/testing only).

---

## 13. ASS Subtitle Engine (`subtitles/`)

Generates professional ASS subtitles per scene. Standards: ≤18 CPS, ≤42 chars/line, ≤2 lines/cue.

### Key files
```
subtitles/
├── engine.py          # SubtitleEngine — orchestrates all sub-stages
├── segmenter.py       # semantic grouping + two-line balancing
├── timing.py          # gap/overlap repair, duration clamping
├── validator.py       # CPS, line-length, orphan checks
├── typography.py      # display normalization
├── writer.py          # SRTWriter
├── ass/
│   ├── writer.py      # ASSWriter — primary output
│   └── theme_manager.py  # ThemeManager with 4 presets
└── editor/            # Subtitle Intelligence Engine V2 (see §14)
```

### SubtitleEngine public API

```python
engine = SubtitleEngine.from_settings(settings)

# Single-call outputs (legacy / backward-compat)
engine.build(...)                    # → SRT string
engine.build_report(...)             # → (SRT, SubtitleReport)
engine.build_both(...)               # → (ASS, SRT, SubtitleReport)

# New — for editing passes
cues, report = engine.build_cues(...)  # → (list[SubtitleCue], SubtitleReport)
engine.ass_writer.write(cues)          # → ASS string
engine.srt_writer.write(cues)          # → SRT string
```

Output: `scene-NNN.ass` (primary for rendering) + `scene-NNN.srt` (compatibility).

---

## 14. Subtitle Intelligence Engine V2 (`subtitles/editor/`)

**Spec:** `docs/video/SUBTITLE_INTELLIGENCE_ENGINE_V2.md` (internally titled V3).
**Enabled by:** `SUBTITLE_EDITOR_ENABLED=true` in `.env` (off by default).

### Architecture

```
subtitles/editor/
├── __init__.py          # exports SubtitleEditingEngine, SubtitleEditorProvider, models
├── provider.py          # SubtitleEditorProvider ABC + CueInput, CueOutput, EditResult
├── prompt.py            # EDITORIAL_SYSTEM_PROMPT (verbatim spec, APPENDIX excluded)
├── engine.py            # SubtitleEditingEngine — all business logic
├── factory.py           # get_subtitle_editor_provider(settings)
└── providers/
    ├── llm_provider.py  # LLMSubtitleEditor wraps existing LLMProvider
    └── mock.py          # MockSubtitleEditor (passthrough, score=100, no API)
```

### Engine control flow

1. **Build inputs** from `list[SubtitleCue]` → `list[CueInput]` (cue_id, timestamps, CPS, original_text)
2. **For each pass (up to `max_passes=3`):**
   - Call `provider.edit_cues()` — single LLM call, full cue list (document-first)
   - Validate: count == input count AND cue_id sets match 1:1. If mismatch → retry with error message (up to `max_retries=3`)
   - Word-integrity check: compare words against TRUE originals (regex `[a-zA-Z0-9']+`). Revert any cue whose word sequence changed.
   - Advance `working_cues` with this pass's output (iterative refinement)
   - Track `best_cues` = highest-scoring version across all passes
   - If `quality_score >= pass_threshold (95)` → stop early
3. **Fallback:** if all passes exhausted below 95, output best-scoring version ("BEST EFFORT")
4. **Debug files** (when `subtitle_debug=True`): `workspace/jobs/<id>/subtitle-debug/editor/{scene-id}-original.srt`, `-edited.srt`, `-diff.md`

### Key design invariants

- `cue_id` = `SubtitleCue.index` (1-based, scene-local)
- `original_text` = `"\n".join(cue.lines)` — line breaks preserved as `\n`
- Word validation always against TRUE original TTS text, never the working copy
- `working_cues` always advances (pass N inputs = pass N-1 output); `best_cues` tracks highest score
- Quality score is bundled into the same LLM call response — no second round-trip
- Provider handles: LLM call + JSON parsing. Engine handles: cue_id validation, retry, word check, scoring loop, debug files.

### LLM response format

```json
{
  "edited_cues": [{"cue_id": 1, "text": "edited — \\n for two-line break"}, ...],
  "quality_score": 87,
  "failed_axes": ["line_balance"],
  "notes": "..."
}
```

### Settings

| Setting | Default | Purpose |
|---|---|---|
| `subtitle_editor_enabled` | `False` | Enable LLM editorial pass in CaptionPipeline |
| `subtitle_editor_provider` | `"llm"` | `"llm"` or `"mock"` |
| `subtitle_editor_max_passes` | `3` | Max editorial passes before BEST EFFORT |
| `subtitle_editor_pass_threshold` | `95.0` | Score to stop iterating early |
| `subtitle_editor_max_retries` | `3` | Retries per pass on cue_id mismatch |

### CaptionPipeline integration

```python
cues, report = engine.build_cues(...)         # build raw cues
if editor: cues = editor.edit(cues, ...)      # optional editorial pass
ass = engine.ass_writer.write(cues)           # serialise
srt = engine.srt_writer.write(cues)
# write to disk
```

---

## 15. TTS & Voice Pipeline

`VoicePipeline` → SpeechOptimizer → SpeechFormatter → EmotionEngine → ContemplativePacingEngine → Edge TTS / ElevenLabs.

**Pacing profiles:** `normal | documentary | spiritual | meditation | slow_reflection`
`spiritual`: 500–700 ms normal pause, 1.2–1.8 s important, 2.0–2.5 s major-realization.

Output: `audio/scene-NNN.mp3` + `scene-NNN.timing.json` (word timestamps, used by ChaptersGenerator).

---

## 16. Scene Planning — Cultural & Visual Intelligence

Entry: `ScenePipeline` → LLM using `_VISUAL_PROMPTS_TEMPLATE` in `agents/prompts/scene_planner.py`.

**LLM prompt sections (in order):**

1. BANNED patterns — opening phrase ban, camera-as-subject ban, narration-copy ban, cliché ban
2. CULTURAL MIXING ban — all elements must belong to one cultural world
3. CLOTHING & CULTURAL AUTHENTICITY — mandatory clothing for every human scene; context table; never bare torso unless authentic exception
4. HUMAN SUBJECT QUALITY — 7 mandatory quality markers; Subject Dominance Rule for wide shots
5. CULTURAL AUTHENTICITY — one cultural context locked across scenes; 8 context mappings
6. CHARACTER BIBLE — one physical description locked across all scenes
7. STORYBOARD — 6-step pre-writing plan
8. PER-SCENE INTERNAL REASONING (A–J): A = cultural context + clothing check; B–J = core meaning, emotion, metaphor, subject, environment, shot type, lighting, palette, self-critique
9. PROMPT STRUCTURE — 10-element flowing paragraph
10. VISUAL CONTINUITY — protagonist consistency, gradual color temperature arc
11. WRITING RULES — 60–90 words, no "A person" opener

---

## 17. Brand Template System V1

**Spec:** `docs/branding/BRAND_TEMPLATE_SYSTEM_V1.md`
**Single source of truth:** `config/brand_config.yaml` (repo root)
**Module:** `src/ytfactory/branding/` (`config.py`, `validator.py`, `__init__.py`)

### YAML structure (6 sections)
`channel_name` | `opening` | `closing` | `cta` | `signature` | `voice` | `branding`

### Required script structure (enforced by LLM prompts + BrandValidator)
```
Hook → Channel Welcome (opening.text) → Teaching → Reflection
     → Brand Signature (closing.text) → CTA (cta.text) → Closing Quote (signature.text)
```

### Key design points

- **`get_brand_config()`** — singleton with lazy load; `reset_brand_config_cache()` for test isolation
- **`ContentSection.text()`** — joins multiline YAML into clean single-line string
- **`_load_brand()`** returns 3-tuple `(channel_name, cta_text, closing_brand_text)`. Callers needing only `channel_name` must use `channel_name, *_ = _load_brand()` (not 2-tuple unpack).
- **Backward compatibility** — falls back to Atma Theory defaults if `config/brand_config.yaml` absent
- **No "Atma Theory" in production code** — only in `branding/config.py` default constants and `config/brand_config.yaml`
- **Public API:** `get_welcome()`, `get_closing()`, `get_closing_brand()`, `get_cta()`, `get_transition()`

### BrandValidator — 7 checks
1. Hook exists in first 15%
2. Channel Welcome (opening) appears in first 30%
3. Brand Signature (closing.text) appears in last 45%
4. CTA appears in last 45%
5. CTA appears exactly once
5b. **Brand assertion before CTA** — `closing_pos < cta_pos` (reversal → issue)
6. Closing quote appears after CTA
7. Brand voice identity present

### Wiring
- `agents/prompts/script_writer.py` — `build_write_script_prompt`: 10-step structure, step 8 = Brand Signature (`closing_brand`), step 9 = CTA, step 10 = Closing Quote
- `agents/prompts/script_enhancer.py` — `_ENHANCER_TEMPLATE` CHANNEL FRAME: all 4 brand elements including `{closing_brand}`
- `agents/nodes/script_writer.py` — imports `get_closing_brand`, passes to prompt builder
- `agents/nodes/script_enhancer.py` — imports `get_closing_brand`, passes to prompt builder
- `agents/prompts/script_writer.py` — `build_review_prompt` checklist includes Brand Signature check

---

## 18. Publishing Layer (`publish/`)

`PublishPipeline.run(project_id)` writes complete YouTube package to `publish/`:
`ChaptersGenerator`, `TitleGenerator`, `SEOGenerator`, `DescriptionGenerator`, `ThumbnailGenerator` (1280×720), `UploadPackageGenerator`.

`ChaptersGenerator` reads real audio duration from `timing.json` last entry's `"end"` field (falls back to `scene["duration_seconds"]` if absent).

---

## 19. Provider System

Business logic never imports concrete providers — calls factory functions:

| Type | Base | Implementations | Setting |
|---|---|---|---|
| LLM | `providers/llm/base.py` | Gemini, Groq, OpenAI, Ollama, Anthropic | `LLM_PROVIDER` |
| Search | `providers/search/base.py` | Tavily | `SEARCH_PROVIDER` |
| Image | `providers/image/base.py` | HuggingFace, Gemini, Pollinations, A1111, Mock | `IMAGE_PROVIDER` |
| TTS | `providers/tts/base.py` | Edge TTS, ElevenLabs | `TTS_PROVIDER` |
| Subtitle Editor | `subtitles/editor/provider.py` | LLMSubtitleEditor, MockSubtitleEditor | `SUBTITLE_EDITOR_PROVIDER` |

**Negative prompt split:** `{"huggingface", "a1111", "automatic1111", "sd-webui"}` support native negative_prompt API; others get anatomy + clothing reinforcement in positive prompt.

---

## 20. Implemented Specifications

| Spec | Status |
|---|---|
| IMAGE_PROMPT_ENGINE_V4 | ✅ |
| HUMAN_QUALITY_AND_SUBJECT_VALIDATION_V1 | ✅ |
| SCRIPT_GENERATION_RULES_V1 | ✅ |
| SCRIPT_BRANDING_V1 | ✅ |
| BRAND_TEMPLATE_SYSTEM_V1 | ✅ |
| SCRIPT_PACING_AND_DURATION_RULES_V2 | ✅ |
| SPEECH_OPTIMIZER_V1 | ✅ |
| TTS_VOICE_GENERATION_V2 | ✅ |
| ASS_SUBTITLE_ENGINE_V1 | ✅ |
| SUBTITLE_INTELLIGENCE_ENGINE_V1 | ✅ |
| **SUBTITLE_INTELLIGENCE_ENGINE_V2** | ✅ |
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
| Clothing & Cultural Authenticity Policy | ✅ (no separate spec; in `clothing_policy.py` + scene_planner) |

---

## 21. Test Suite

**Current count: 1554 passed, 0 failed** (as of 2026-07-06).

Key test files:

| File | Tests | Coverage |
|---|---|---|
| `tests/subtitles/test_subtitle_editor.py` | 44 | Subtitle Intelligence Engine V2 |
| `tests/test_incremental.py` | 53 | Manifest, change detector, scene workspace, engine, reporter |
| `tests/test_clothing_policy.py` | 53 | detect_violation, is_authentic_exception, apply_clothing_policy |
| `tests/test_human_quality_validation.py` | 47 | human_detector + HumanValidator |
| `tests/test_brand_template_system.py` | ~35 | YAML loading, BrandValidator 7 checks, no-hardcoded-names |
| `tests/test_bgm.py` | ~25 | BGMConfig defaults, filter architecture, Settings fields |
| `tests/test_image_prompt_engine.py` | — | prompt engine + enrich + review_prompt |
| `tests/test_video_pipeline_duration.py` | — | audio duration resolution |

API-dependent files at repo root (require live keys, excluded from `tests/`):
`test_gemini_image.py`, `test_hf_image.py`

---

## 22. Domain Models

`src/ytfactory/domain/` — pure dataclasses/Pydantic (no I/O):
- `Project` — metadata + stage status (`pending|running|completed`)
- `LLMResponse`, `SearchResult`, `ImageRequest`

`ProjectRepository` (`storage/project_repository.py`) — serializes `Project` to `project.json`.

```python
# shared/constants.py
WORKSPACE_DIR = "workspace/jobs"
PROJECT_FILE = "project.json"
```

---

## 23. Test Patterns

```python
# Patching WORKSPACE_DIR — always patch in the consuming module, NOT in shared.constants
monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))
monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))

# Brand config isolation
from ytfactory.branding.config import reset_brand_config_cache
reset_brand_config_cache()

# Settings defaults — use model_fields, not self._s(), for .env-independence
Settings.model_fields["bgm_volume"].default
```

---

## 24. Known Design Decisions & Gotchas

| Decision | Reason |
|---|---|
| "human" excluded from `_HUMAN_INDICATORS` | "natural human anatomy" phrase causes false detection |
| Sadhu/yogi/ascetic not in `_HUMAN_INDICATORS` | `apply_clothing_policy` handles via `is_authentic_exception()` |
| Clothing policy runs AFTER human quality reinforcement | Human markers must be in prompt before clothing evaluation |
| `trim=duration` before subtitles in `render_continuous` | Zoompan outputs `d²×fps` seconds without the trim gate |
| BGM uses two-path filter (floor + sidechain-compressed main) | True minimum floor requires a separate always-on path; sidechaincompress alone cannot guarantee a floor |
| `_load_brand()` returns 3-tuple — use `channel_name, *_ = _load_brand()` | Added `closing_brand` as third element; 2-tuple unpack raises ValueError |
| BrandValidator check 5b: brand signature must precede CTA | Script structure: Reflection → Brand Signature → CTA → Closing Quote |
| `subtitle_editor_enabled=False` default | LLM editorial pass costs tokens per scene; must be explicitly opted in |
| Subtitle engine `build_cues()` writes debug files pre-edit | Debug reflects raw generated cues; editor debug (`-original.srt`) is the same but stored separately |
| Subtitle word validation always against TRUE original | Prevents word drift accumulating across iterative passes |
| `working_cues` always advances in multi-pass subtitle editing | Each pass refines the previous; `best_cues` tracks the score, not the recency |
| `ytfactory run --resume` routes to `BuildPipeline.run_incremental`, NOT LangGraph | LangGraph has no selective stage-skipping mechanism |
| Locked scenes skipped silently | `needs_run()` returns False; locked guard in `SceneWorkspace.mark_needs_revision()` |
| `scene-plan.json` is central — never delete it | Images, voice, captions, video all read from it |
| `.gitignore build/` matches `src/ytfactory/build/` | Use `git add -f src/ytfactory/build/` |

---

## 25. Boot Instructions for New Claude Sessions

1. Read `docs/context/MASTER_CONTEXT_V4.md` (this file) first.
2. Read `CLAUDE.md` for commands and architecture notes.
3. Check memory at `/home/santosh/.claude/projects/-home-santosh-pvt-files-youtube-factory/memory/MEMORY.md`.
4. **Before implementing any new V1 spec:** read the spec, perform an architecture review, identify all interaction surfaces with existing V1s, get user approval before writing production code. Never regress existing V1s.
5. After any code change: `uv run ruff check src/ && uv run ruff format src/` then `uv run pytest tests/ -q` — confirm 0 failures.
6. **Execute Mode by default** — do NOT enter Plan Mode or spawn multiple agents unless explicitly requested.
7. **.env policy** — comment out old value, add new on next line, never overwrite.
