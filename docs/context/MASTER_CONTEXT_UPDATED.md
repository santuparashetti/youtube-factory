---
name: master-context
description: "Complete project context — architecture, all V1 specs, provider stack, invariants, working rules. Single file for any new session."
metadata: 
  node_type: memory
  type: project
  originSessionId: 38c1e454-acc9-469d-84a6-b1a6c2b9df1c
---

# YouTube Factory — Master Context

**Repo root:** `/home/santosh/pvt-files/youtube-factory`  
**Stack:** Python 3.10, uv, Pydantic v2, LangGraph, Typer, FFmpeg  
**Test count:** 2161 passing (as of 2026-07-12)  
**Always run from repo root** — `.env` and `workspace/` are resolved relative to CWD.

## 2026-07-12 — Phase 1 Settings split complete (commits 4df0ecf, e9f9183, 4e9d46b, 6516da3)
Split monolithic `ytfactory.config.settings.Settings` (117 fields) into:
  - `video_core.config.SharedSettings` — 27 fields (API keys, provider
    selectors, model names, provider-config values consumed by
    video_core providers)
  - `ytfactory.config.Settings(SharedSettings)` — remaining ~90 fields
    (pipeline/quality/content-specific), inherits all SharedSettings
    fields so every existing `settings.<field>` call site is unchanged
3 known-dead fields (kokoro_language, whisperx_model, request_timeout)
intentionally left in place — separate cleanup, not part of this split.
`check_layering.py`: `ytfactory.config.settings` removed from `KNOWN_BUCKET_C`
allowlist. One remaining Bucket-C exception: `ytfactory.shared.constants`
(tracked for Phase 2).
Test count unchanged: 2161 passing, 0 failing throughout.

## 2026-07-12 — Phase 0 structural extraction complete (commit 06c358b)
Moved to `video_core`: `providers/{llm,search,image,tts-excl-pacing,vision}`,
`models/` (LAMM), `domain/{llm,search,image}.py`.
Stayed in `ytfactory`: everything else (review, branding, publish, bgm,
agents, build, scenes, `providers/tts/pacing/`, `domain/project.py`).
Test baseline unchanged: **2159 passing, 0 failing**.
Layering enforced via `scripts/check_layering.py`.
Known allowlisted Bucket-C exceptions (tracked for Phase 1, not yet
extracted): `ytfactory.config.settings`, `ytfactory.shared.constants`.

---

## Working Rules (user preferences)

- **Execute Mode by default** — analyze briefly, implement immediately. No Plan Mode unless user says "plan" or requests architectural review.
- **Before any new V1 spec** — do architecture review + integration plan first, wait for approval, then implement. Never regress existing V1s.
- **.env changes** — always comment out the old line, add new value on next line. Never overwrite.
- **No multi-agent** unless user explicitly requests parallel execution.
- Responses concise. No long pre-implementation writeups.

---

## Two Execution Paths

### 1. Agentic pipeline — `ytfactory run <topic>` / `uv run ytfactory` (wizard)
LangGraph graph in `src/ytfactory/agents/`. Nodes: research → script_writer → script_enhancer → scene_planner → image_generator (parallel) + voice_generator (parallel) → video_renderer → concatenator.  
State: `VideoState` in `agents/state.py`. Entry: `run_pipeline()` in `agents/runner.py`.  
`--resume --project <id>` skips the LangGraph graph entirely → routes to `BuildPipeline.run_incremental()`.

**Interactive wizard:** `uv run ytfactory` (no subcommand) launches `src/ytfactory/cli/wizard.py`. Must be run from repo root or `.env` won't load — Settings defaults fall back to `llm_provider="anthropic"` which fails with an empty key.

### 2. Sequential pipeline — `ytfactory build <id>`
`BuildPipeline` in `src/ytfactory/build/pipeline.py`. Calls each pipeline class in order. Supports incremental mode via `run_incremental()`.

**Full manual workflow:**
```bash
ytfactory create "Title"
ytfactory import-script <id> script.txt
ytfactory plan-scenes <id>
ytfactory generate-images <id>
ytfactory generate-voice <id>
ytfactory generate-captions <id>
ytfactory render <id>
ytfactory review <id>
ytfactory remediate <id>
ytfactory publish <id>
```

---

## Source Layout (post Phase 0)

```
src/
├── video_core/          # Phase 0 extraction (2026-07-12, commit 06c358b)
│   ├── providers/       # llm, search, image, tts (excl. pacing/), vision
│   ├── models/          # LAMM: manager, registry, bundle, capabilities
│   ├── domain/          # LLMResponse, SearchResult, ImageRequest
│   └── config/          # SharedSettings (Phase 1, 2026-07-12)
│
└── ytfactory/           # unchanged product code — review, publish, bgm,
                         # branding, agents, build, scenes, providers/tts/pacing/,
                         # domain/project.py, config/, everything else
```

**Layering rule:** `video_core` must not import from `ytfactory`. Enforced by `scripts/check_layering.py`. Known open Bucket-C deps (Phase 1): `ytfactory.config.settings`, `ytfactory.shared.constants`.

---

## Current Provider Stack (`.env` as of 2026-07-09)

| Provider type | Setting | Current value |
|---|---|---|
| LLM | `LLM_PROVIDER` | `anthropic` → `OpenAICompatibleProvider` |
| LLM model | `ANTHROPIC_MODEL` | `claude-haiku-4-5` via LiteLLM proxy |
| Search | `SEARCH_PROVIDER` | `tavily` |
| Image | `IMAGE_PROVIDER` | `huggingface` (FLUX.1-schnell) |
| TTS | `TTS_PROVIDER` | `kokoro` (KokoroProvider — local neural TTS) |
| WhisperX | `WHISPERX_ENABLED` | `true` |
| WhisperX device | `WHISPERX_DEVICE` | `cpu` |
| Resolution | `IMAGE_WIDTH/HEIGHT` | `1280×720` |
| BGM | `BGM_ENABLED` | `true` |
| Render profile | `RENDER_PROFILE` | set per wizard run |

**Provider factory pattern:** business logic calls `get_llm_provider(settings)` / `get_image_provider(settings)` / `get_tts_provider(settings)` — never imports a concrete provider directly.

| Provider type | Base class | Implementations | Setting key |
|---|---|---|---|
| LLM | `video_core.providers.llm.base` | Gemini, Anthropic (OpenAI-compat), Groq, Ollama | `LLM_PROVIDER` |
| Search | `video_core.providers.search.base` | Tavily | `SEARCH_PROVIDER` |
| Image | `video_core.providers.image.base` | HuggingFace, Gemini | `IMAGE_PROVIDER` |
| TTS | `video_core.providers.tts.base` (pacing engine stays at `ytfactory.providers.tts.pacing`) | Kokoro, Edge TTS | `TTS_PROVIDER` |
| Vision | `video_core.providers.vision.base` | Local (Qwen2.5-VL via llama.cpp), Mock | `VISION_REVIEW_PROVIDER` |

`get_<type>_provider()` factory functions moved with their base classes — call sites unchanged, only import paths changed.

---

## All Implemented V1 Specs (chronological)

### 1. VIDEO_QUALITY_REVIEW_ENGINE_V1
Multi-layer quality gate in `src/ytfactory/review/`. Runs after `ytfactory render`.

- **Layer 1 — Stage checks** (`review/stages/`): asset_integrity, timeline, content, production_quality
- **Layer 2 — Validation rules** (`review/validation/`): 9 validators (script, narration, subtitle, image, human, motion, audio, rendering, story). Each rule: structured `ValidationResult` with rule ID, severity, evidence, confidence, `responsible_engine`.
- **Layer 3 — Root Cause Analysis** (`review/rca/`): groups failures by engine, builds remediation chains, detects recurring patterns. Writes 4 files.
- **Layer 4 — Quality Scoring** (`review/scoring/`): 8 category scorers (point-budget model), weighted average → 0–100 score, letter grade A+→F, PASS/FAIL. Writes 4 files.
- **Layer 5 — Engine Feedback Loop** (`review/efl/`): 12 engine targets, recurring issue escalation. Writes 5 files including cross-run `recurring-patterns.json`.
- **Layer 6 — Debug mode** (`review/debug/`): `DebugLevel.OFF|BASIC|DETAILED|VERBOSE`. Zero overhead when OFF. Writes 7 files.
- **Layer 7 — Auto Remediation** (`review/remediation/`): plan → execute → re-validate loop (up to `max_retries`). `RemediationAction` requires `confidence: int` and `rationale: str` fields. `dry_run=True` safe. Writes 4 files.

**Output directory:** `workspace/jobs/<id>/review/` — 17+ files.

---

### 2. Publishing Layer
`src/ytfactory/publish/`. Runs after `ytfactory remediate` (or `review`).

Generators (in pipeline order): ChaptersGenerator, TitleGenerator, SEOGenerator, DescriptionGenerator, PinnedCommentGenerator, ThumbnailGenerator, UploadPackageGenerator.  
Output: `workspace/jobs/<id>/publish/` — title.txt, alternate-titles.txt, description.md, keywords.txt, hashtags.txt, youtube-tags.txt, chapters.txt, **pinned-comment.txt**, thumbnail.png, thumbnail-variants/, youtube-metadata.json.  
`PublishConfig(skip_thumbnail=True)` skips image API calls.

**PinnedCommentGenerator** (`publish/generators/comment.py`):  
- Generates an engaging first pinned comment (2–3 sentences, ≤500 chars) using the LLM.  
- References a specific idea/emotion from the video — not generic.  
- Always ends with one clear question to spark viewer replies.  
- Result: `PinnedCommentResult(text, char_count, has_question)` — also embedded in `youtube-metadata.json` under `"pinned_comment"`.  
- Validation warning fires if the comment contains no question mark.  
- When adding new LLM mock side_effects in publish tests, include a 4th response for the pinned comment call.

---

### 3. HUMAN_QUALITY_AND_SUBJECT_VALIDATION_V1
**Files:** `src/ytfactory/images/human_detector.py`, `review/validation/rules/human.py`

- `detect_human_presence(prompt)` — whole-word regex against `_HUMAN_INDICATORS`. **"human" NOT in indicators** (false positive with "natural human anatomy").
- `add_human_quality_reinforcement(prompt)` — appends 7 quality phrases.
- `apply_subject_dominance_rule(prompt, shot_type)` — wide/establishing/drone shots get "subject remains visually prominent".
- `compute_sharpness(img)` — Pillow FIND_EDGES stddev. Retry threshold: 12.0 (pipeline), validation threshold: 8.0 (HUM_003).
- `has_human_quality_reinforcement()` requires ≥ 2 markers.
- Settings: `image_human_max_retries=2`, `image_human_min_sharpness=12.0`.
- Review rules: HUM_001 (quality markers), HUM_002 (subject dominance), HUM_003 (sharpness).

---

### 4. INCREMENTAL_RENDERING_AND_SCENE_WORKSPACE_V1
**Module:** `src/ytfactory/incremental/` + `src/ytfactory/scene/`

**Incremental build** — SHA-256 checksum manifest (`.pipeline-manifest.json`) detects changed files, skips clean stages, runs only dirty stages + their downstream chain.

**Key CLI:**
```bash
ytfactory build <id> --resume              # skip unchanged stages
ytfactory build <id> --force-images        # force images + downstream
ytfactory build <id> --force-narration     # force voice + downstream
ytfactory build <id> --force-scene 8       # force one scene entirely
ytfactory build <id> --scene 3 --force-video
ytfactory scene list/approve/reject/lock/unlock/review <id>
```

**Scene states:** Draft → Needs Review → Approved → Locked → Needs Revision  
**Locked scenes NEVER auto-regenerated** — only `scene unlock` or `--force-scene N` overrides.  
`scene-status.json` in `workspace/jobs/<id>/scenes/`.

`ytfactory run <topic> --project <id> --resume` skips LangGraph; routes to `BuildPipeline.run_incremental()`.

---

### 5. Clothing & Cultural Authenticity Policy
**File:** `src/ytfactory/images/clothing_policy.py`

- `detect_violation(prompt)` — 18 violation terms (nude, naked, shirtless, bare-chested, bare torso, topless, no shirt, nudity, skimpy, revealing clothing…). "bare feet/tree/arms" NOT flagged.
- `is_authentic_exception(prompt)` — Hindu sadhus, Naga sadhus, Jain monks (Digambara), Buddhist/Zen/Theravada monks, ancient ascetics, vedic ascetics, yogis, indigenous traditional, historical bathing rituals.
- 4-branch decision: no human → pass; violation + exception → respectful framing; violation + no exception → enforce clothing; no violation + human + no clothing → infer clothing from context.
- **Gotcha:** "sadhu", "yogi", "ascetic" NOT in `_HUMAN_INDICATORS` — `apply_clothing_policy` uses `is_authentic_exception` as secondary human-presence signal.
- Runs in `enrich_for_provider()` after human quality reinforcement.
- Also enforced at LLM instruction level via `scene_planner.py` prompt.

---

### 6. Cinematic Motion Engine (continuous renderer)
`video/ffmpeg.py` → `render_continuous()` — single-pass filter_complex H.264 encode. All scenes in one stream, no GOP boundaries. Fixes YouTube transcoder pause issue from stream-copy concat.

**Critical fix in filter_complex:** `trim=duration={dur:.4f},setpts=PTS-STARTPTS` added BEFORE subtitle burn-in. Without trim, zoompan outputs `d` frames PER input frame when fed a video stream → `dur² × fps` seconds total (the "duration bug").

---

### 7. BRAND_TEMPLATE_SYSTEM_V1
**Spec:** `docs/branding/BRAND_TEMPLATE_SYSTEM_V1.md`  
**Single source of truth:** `config/brand_config.yaml` (repo root)  
**Module:** `src/ytfactory/branding/` — `config.py`, `validator.py`, `__init__.py`

**Script structure enforced:**
```
Hook → Channel Welcome (opening.text) → Teaching → Reflection
     → Brand Signature (closing.text) → CTA (cta.text) → Closing Quote (signature.text)
```

**Key distinctions:**
- `closing.text()` = brand assertion "This is Atma Theory." (before CTA)
- `signature.text()` = closing tagline "Think deeper... Live clearer." (after CTA)

**Wiring:** `script_writer.py` and `script_enhancer.py` nodes both receive `closing_brand` from `get_closing_brand()`.

**`get_brand_config()` singleton** — lazy load. Call `reset_brand_config_cache()` in tests that swap config files.

**BrandValidator:** 6 checks (hook ≥10 words, welcome in first 30%, signature in last 45%, assertion in last 45%, assertion before CTA, tagline after CTA).

---

### 8. SUBTITLE_INTELLIGENCE_ENGINE_V2
**Module:** `src/ytfactory/subtitles/editor/`

Doc-first LLM editorial pass after raw subtitle generation. Improves punctuation, capitalisation, line breaks while preserving all timing exactly.

- `SubtitleEditingEngine` — main orchestrator. Multi-pass: working_cues advances each pass; best_cues = highest score.
- `cue_id` = `SubtitleCue.index` (1-based, scene-local).
- Retry-on-mismatch: cue_id set comparison → retry with error in prompt.
- Word integrity validated against TRUE original TTS text, not working copy.
- `SubtitleEngine` additions: `build_cues()` → raw cues without writing files; `ass_writer` property; `srt_writer` property.

**Settings (all off by default):**
```
SUBTITLE_EDITOR_ENABLED=false
SUBTITLE_EDITOR_PROVIDER=llm    # or "mock" (passthrough, no API)
SUBTITLE_EDITOR_MAX_PASSES=3
SUBTITLE_EDITOR_PASS_THRESHOLD=95.0
SUBTITLE_EDITOR_MAX_RETRIES=3
```

---

### 9. Contemplative Pacing Engine
**Files:** `src/ytfactory/providers/tts/pacing/` — `config.py`, `thought_analyzer.py`, `injector.py`, `models.py`

Three-level thought-based pacing (replaces sentence-level pauses):
- `ThoughtAnalyzer` groups narration into semantic thought blocks; `PauseInjector` inserts silence between blocks.
- Block triggers: contrast opener (But/Yet/However), shift opener (Now/Remember/Consider), **reveal starter** (It is/This is/That is/You are/We are/Life is/Truth is — fires at any length when block has a concept or universal word), short conclusive (≤5 words + concept).
- Block scoring: concept density, universals, negation/paradox, rhetorical question, ellipsis, brevity → INSIGHT / REALIZATION / SMALL pause tier.

**`spiritual` profile pause ranges (current):**
```
small:       800–1200 ms
realization: 1200–1800 ms
insight:     1800–2500 ms   ← reduced from 2500–4000 for natural pacing
```

**Settings:**
```
TTS_PACING_ENABLED=true
TTS_PACING_PROFILE=spiritual    # normal | documentary | spiritual | meditation | slow_reflection
KOKORO_SPEED=0.85               # 1.0 = natural, 0.85 = contemplative
```

**Gotcha:** "It is the presence of everything you have been running from." contains "everything" (in `_UNIVERSALS`) → fires reveal trigger even though no `_MAJOR_CONCEPTS` word present. "This is natural." has neither concept nor universal → does NOT trigger (expected).

---

### 10. KOKORO_PROVIDER_AND_SUBTITLE_ENGINE_UPGRADE_V1
**Spec:** `docs/video/KOKORO_PROVIDER_AND_SUBTITLE_ENGINE_UPGRADE_V1.md`

#### Kokoro TTS Provider
**File:** `src/ytfactory/providers/tts/kokoro.py`  
**Packages required (manual install, not in pyproject.toml):** `uv pip install kokoro soundfile` + `apt install espeak-ng`  
- Local neural TTS, no API key needed. First run downloads ~300 MB model weights.
- Lazy import (`import kokoro` inside methods). WAV → MP3 via FFmpeg subprocess.
- Returns empty word boundaries — WhisperX alignment needed for accurate subtitle timing.
- Settings: `kokoro_voice="am_michael"`, `kokoro_language="en-US"`, `kokoro_speed=0.85`, `kokoro_sample_rate=24000`.
- Activate: `TTS_PROVIDER=kokoro` in `.env`.

#### WhisperX Forced Alignment
**File:** `src/ytfactory/voice/aligner.py`  
**Package required:** `uv pip install whisperx`  
- Forced alignment (wav2vec2 phoneme model per language) — NOT transcription. No configurable model size.
- `WHISPERX_MODEL` setting is reserved for future transcription; currently unused for alignment.
- `align(narration, audio_path, *, device="cpu", language="en")` — no `model_size` param.
- Output: `alignment.json` alongside mp3 → `{version: "whisperx_v1", words: [{word, start, end, score}], sentences, confidence}`.
- `save_alignment()`, `load_alignment()`, `boundaries_from_alignment()` utilities.
- Activate: `WHISPERX_ENABLED=true` in `.env`.

**Wiring in `VoicePipeline`:** after audio generation, if `whisperx_enabled=True` and `alignment.json` doesn't already exist → runs alignment and saves file.

**Wiring in `CaptionPipeline`:** prefers `alignment.json` over `timing.json` for word boundaries when present.

#### Semantic Subtitle Segmentation
**File:** `src/ytfactory/subtitles/segmenter.py`  
5-priority system: (1) sentence terminal → (2) clause terminal → (3) natural pause (PAUSE_BREAK_THRESHOLD_S=0.18, PAUSE_STRONG_THRESHOLD_S=0.35) → (4) CPS → (5) chars.  
`SubtitleEngine.from_settings()` reads `subtitle_segmentation_mode` (default: `"semantic"`).  
Setting: `SUBTITLE_SEGMENTATION_MODE=semantic` (or `legacy`).

#### New Review Rules (SUBT_007–011)
In `review/validation/rules/subtitle.py`:
- **SUBT_007:** orphan function words at cue end
- **SUBT_008:** unbalanced 2-line cues (ratio < 0.4)
- **SUBT_009:** duplicate consecutive cues
- **SUBT_010:** cue duration < 0.3s or > 8.0s
- **SUBT_011:** subtitle density (narration_words // 25 minimum cues)
- `_parse_srt_blocks` cue_text now uses `"\n".join` (not `" ".join`) — SUBT_006 Jaccard normalizes with `.replace("\n", " ")`, SUBT_003 CPS similarly.

#### `regenerate_alignment` Remediation Strategy
In `review/remediation/executor.py`. Deletes `*.alignment.json` files, calls `VoicePipeline(settings).run(project_id)` only when `whisperx_enabled=True`. Preserves mp3 files.  
**Test patching:** Settings is a lazy local import inside `_regenerate_alignment` → patch via `"ytfactory.config.settings.Settings"` (not `"ytfactory.review.remediation.executor.Settings"`).

---

### 11. BGM_MIXING_ENGINE_V2
**Spec:** `docs/video/BGM_MIXING_ENGINE_V2.md`  
**New files:** `src/ytfactory/bgm/vad.py`, `src/ytfactory/bgm/debug.py`  
**Modified:** `bgm/config.py`, `bgm/mixer.py`, `bgm/pipeline.py`, `video/pipeline.py`, `config/settings.py`, `review/validation/rules/bgm.py`, `review/engine.py`

#### Architecture
Extends the existing two-path floor+main sidechaincompress architecture. No redesign.

**Key V2 addition — agate phrase grouping on sidechain:**
```
[nar_raw]agate=threshold={duck_threshold}:hold={phrase_gap_ms/1000}:attack=0.015:release=0.350:range=0.01[nar_sc]
```
The `hold` parameter keeps the gate open across inter-word gaps ≤ `phrase_gap_ms` → music stays ducked for the whole phrase, eliminating inter-word pumping. Long silence recovery (>2s) happens naturally via sidechaincompress release=350ms (reaches ≥99% of target).

#### VAD module (`bgm/vad.py`)
Uses FFmpeg `silencedetect` (no new deps). `detect_speech(audio_path, phrase_gap_ms=300)` → `SpeechTimeline(segments, total_duration, speech_ratio)`. Each `SpeechSegment` has `start`, `end`, `energy` (normalised from volumedetect mean).

#### Debug output (`bgm/debug.py`)
`BGMDebugWriter(project_dir).write(timeline, mix_profile, ffmpeg_filter)` — writes 5 files to `workspace/jobs/<id>/bgm-debug/`: `speech_timeline.json`, `ducking_events.json`, `mix_profile.json`, `ffmpeg_filter.txt`, `audio_levels.csv`.

#### New compressor defaults (V2)
| Setting | Old | New (V2) |
|---|---|---|
| `BGM_VOLUME` | 0.35 | 0.30 |
| `BGM_DUCK_FLOOR` | 0.05 | 0.04 |
| `BGM_DUCK_THRESHOLD` | 0.02 | 0.008 |
| `BGM_DUCK_RATIO` | 2.5 | 8.0 |
| `BGM_DUCK_ATTACK_MS` | 50 | 15 |
| `BGM_DUCK_RELEASE_MS` | 600 | 350 |

#### New Settings fields
```
BGM_VAD_ENABLED=true
BGM_VAD_PROVIDER=silero       # reserved; current impl uses ffmpeg silencedetect
BGM_PHRASE_GAP_MS=300
BGM_LONG_SILENCE_MS=2000
BGM_DYNAMIC_DUCKING=true
BGM_RESTORE_CURVE=logarithmic
```

#### New review rules
- **BGM_005 [medium]:** Duck depth — BGM during narration not louder than BGM intro
- **BGM_006 [low]:** Phrase detection active — `bgm-debug/speech_timeline.json` present and non-empty
- **BGM_007 [medium]:** Long silence recovery — BGM volume during >2s silence gap within 4 dB of intro level

BGM_005–007 SKIP when `bgm-debug/speech_timeline.json` absent.

#### Backward compatibility
- Existing `.env` overrides (`BGM_VOLUME=0.24`, `BGM_DUCK_THRESHOLD=0.02`, `BGM_DUCK_RATIO=6.2`) still take precedence over the new code defaults.
- `vad_enabled=False` in `BGMConfig` restores the V1 filter (no agate). Default is `True`.
- `BGMMixer.mix()` gains optional `project_dir: Path | None = None` — existing callers passing 3 args are unaffected.
- **FFmpeg 4.x compatibility (`_ffmpeg_agate_has_hold()`):** The `hold` option in `agate` was added in FFmpeg 5.x. Ubuntu 22.04 ships 4.4.2 which lacks it. `_ffmpeg_agate_has_hold()` (cached probe, `re.search(r"^\s+hold\s", r.stdout, re.MULTILINE)`) detects support at runtime; filter is built without `hold` on FFmpeg 4.x — ducking still works but inter-word phrase bridging is absent. **Gotcha:** `"threshold="` contains `"hold"` as a substring (`t-h-r-e-s-[h-o-l-d]=`) so a plain `"hold" in stdout` is a false positive — must match as standalone option with the regex.
- **Error log tail:** `err[-800:]` not `err[:500]` — FFmpeg always writes its version header first; the first 500 chars never contain the actual error.

#### Incremental build
Already handled — `"bgm": "video"` in `incremental/deps.py` invalidates only the video stage when BGM settings change.

#### BGMLibrary fallback (post-V2 fix)
`BGMLibrary.find_track()` has a **4-level fallback**:
1. Exact `<library_path>/<category>/` subdirectory
2. Flat root files whose filename contains the category keyword
3. Any flat root-level file
4. **Any track in any subdirectory** (new) — fires when the library uses a subdirectory layout but the auto-detected category has no tracks. Prevents silent BGM skip when only some categories are populated.

Before this fix, step 4 was missing — if the auto-detector chose (e.g.) `emotional_documentary` but only `spiritual/` had tracks, BGM was silently skipped even though music was available.

#### `mix-bgm` CLI command (post-V2 addition)
`ytfactory mix-bgm PROJECT_ID [--video PATH]` — applies BGM to an already-rendered `final.mp4`. Use when BGM was disabled during the original render, or after adding tracks to the library. Implemented in `cli/main.py` inline (no separate `bgm/cli.py`); delegates to `BGMPipeline.run()`.

---

### 12a. BGM_ADAPTIVE_MIXING_ENGINE_V3

**Spec:** `docs/video/BGM_ADAPTIVE_MIXING_ENGINE_V3.md`  
**Modified:** `bgm/config.py`, `bgm/mixer.py`, `bgm/vad.py`, `bgm/debug.py`, `bgm/pipeline.py`, `review/validation/rules/bgm.py`, `config/settings.py`, `video/pipeline.py`, `.env.example`

#### Problem solved
V2 `sidechaincompress` with `release=350ms` released too quickly, allowing music to pump during breaths, commas and dramatic pauses. V3 implements a **hold-then-release state machine** via FFmpeg filter parameter tuning:
- `agate hold = 2200ms` (bridges all short pauses ≤ 2.2 s)
- `sidechaincompress attack = 180ms` (cinematic onset, was 15ms)
- `sidechaincompress release = 1800ms` (slow recovery, was 350ms)
- Only silence > 2.2s triggers recovery; full recovery takes a further 1.8s

#### New config fields (`BGMConfig` and `Settings`)
| Field | Default | Description |
|---|---|---|
| `adaptive_mixing` / `BGM_ADAPTIVE_MIXING` | `True` | Enable V3 state machine |
| `hold_after_speech_ms` / `BGM_HOLD_AFTER_SPEECH_MS` | 2200 | Hold timer (ms) |
| `long_silence_threshold_ms` / `BGM_LONG_SILENCE_THRESHOLD_MS` | 2500 | Classification threshold |
| `narration_level_lufs` / `BGM_NARRATION_LEVEL_LUFS` | -30.0 | Target LUFS (review/debug) |
| `music_level_lufs` / `BGM_MUSIC_LEVEL_LUFS` | -17.0 | Target music LUFS |
| `transition_curve` / `BGM_TRANSITION_CURVE` | "ease_in_out" | Curve shape |

`long_silence_ms` default updated 2000 → 2500 to match threshold.

#### New V3 modules in `bgm/vad.py`
- `PauseType` enum: `BREATH` (<200ms), `COMMA` (200–500ms), `DRAMATIC_PAUSE` (500–1500ms), `SENTENCE_PAUSE` (1500–threshold), `LONG_SILENCE` (>threshold)
- `PauseEvent`: classified gap with start/end/duration/pause_type
- `classify_pause(gap_s, threshold_ms)`: pure function, no FFmpeg
- `PauseClassifier`: classifies all gaps in a SpeechTimeline
- `build_speech_timeline_from_kokoro(project_dir, ...)`: reads `audio/scene-NNN.alignment.json` (WhisperX, preferred) or `audio/scene-NNN.timing.json` (TTS, fallback); merges all scenes with cumulative offsets. Returns None when no files found.

#### `BGMMixer._build_filter()` V3 path
When `adaptive_mixing=True`: `agate hold = hold_after_speech_ms/1000`, `sidechaincompress attack=180, release=1800`. When `False`: V2 legacy values (`phrase_gap_ms`, `duck_attack_ms`, `duck_release_ms`).

#### Debug output additions (`bgm/debug.py`)
When `adaptive_mixing=True`, two extra files written to `bgm-debug/`:
- `state_timeline.json` — full state machine trace: FULL/NARRATION_ACTIVE/MUSIC_FEATURE entries with time, bgm_level_approx, note
- `bgm-mix-report.json` — quality summary: pause_classifications, long_silence_windows, pumping_risk ("low" when adaptive, "medium" when not), quality_notes

Existing files updated: `ducking_events.json` now includes `pause_type` on each restore event; `audio_levels.csv` has a new `pause_type` column.

`BGMDebugWriter.write()` now uses Kokoro timestamps as primary source in the mixer (via `build_speech_timeline_from_kokoro`), falls back to `detect_speech` (FFmpeg silencedetect).

#### New review rules
- **BGM_008 [medium]:** No pumping — adaptive_mixing must be True and pumping_risk="low"
- **BGM_009 [medium]:** Smooth transitions — attack ≥ 100ms, release ≥ 500ms (warns on V2 legacy values)
- **BGM_010 [medium]:** Narration not masked — intro (BGM only) must not be louder than narration body by > 3 dB

BGM_008–010 SKIP when `bgm-debug/bgm-mix-report.json` (008/009) or `speech_timeline.json` (010) absent.
ValidationRunner now runs **10 BGM rules** (was 7).

#### Test count
1793 → **1856** (+63 new V3 tests across: PauseClassifier, classify_pause, BGMConfigV3, BGMMixerV3Filter, SettingsBGMV3Fields, BGMDebugWriterV3, KokoroTimestampReader, BGMV3ReviewRules)  
1856 → **1929** (+73 new Model Bundle Architecture tests in `tests/test_model_bundle.py`)

---

### 12. PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM
**Spec:** `docs/plug-and-play-setup/PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM_FINAL.md`  
**New files:** `src/ytfactory/bootstrap/` package (8 modules), `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`, `tests/test_bootstrap.py`  
**Modified:** `doctor/pipeline.py`, `doctor/cli.py`, `doctor/models.py`, `cli/main.py`, `.gitignore`

#### Bootstrap Package (`src/ytfactory/bootstrap/`)
- `engine.py` — `BootstrapEngine`: orchestrates setup/doctor/validate/repair/version_info
- `workspace.py` — creates all required dirs; idempotent
- `config_validator.py` — reads `.env` directly (not via Settings) so tests using tmp dirs work; checks LLM/search/image provider keys
- `provider_validator.py` — API key presence + TCP reachability check for each provider
- `env_checker.py` — Python version, FFmpeg/ffprobe, Git, Torch, fonts
- `healer.py` — SelfHealingEngine: missing dirs, permissions, broken symlinks
- `model_bootstrap.py` — WhisperX and Kokoro model readiness checks; lazy download on first use
- `version_manager.py` — `bootstrap-manifest.json` read/write; `BOOTSTRAP_VERSION="1.0.0"`
- `report.py` — writes `environment-report.json`
- `models.py` — `CheckStatus`, `CheckResult`, `BootstrapResult`; WARNING is non-blocking (`success` = no ERRORs)

#### New CLI Commands
All idempotent and safe to repeat:
```bash
ytfactory setup [--force]     # full first-run bootstrap + manifest
ytfactory doctor              # health check (no mutations)
ytfactory validate            # config + provider only (lightweight)
ytfactory repair              # self-healing only
ytfactory clean [--logs] [--cache]  # temp dir cleanup
ytfactory reset [--yes] [--workspace]  # clear manifest + report
ytfactory update              # force re-validate + update manifest
ytfactory version             # print versions + manifest state
```

#### Docker Infrastructure
- **`Dockerfile`** — multi-stage (base → builder → production); Python 3.11-slim + uv + FFmpeg + espeak-ng + fonts
- **`docker-compose.yml`** — two services (cpu default, gpu with `--profile gpu`); 4 named volumes: `ytfactory_workspace`, `ytfactory_cache`, `ytfactory_models`, `ytfactory_logs`
- **`.env.example`** — complete template for all API keys + provider settings
- **`.dockerignore`** — excludes workspace, models, cache, .env from build context

#### Quick Start (fresh machine)
```bash
git clone <repo> && cd youtube-factory
cp .env.example .env  # fill in API keys
docker compose up -d
docker exec youtube-factory ytfactory setup
docker exec youtube-factory ytfactory doctor
docker exec youtube-factory ytfactory build <project-id>
```

#### Key Invariants
- `BootstrapResult.success` = True when no ERRORs (WARNINGs are non-blocking)
- `validate_config` reads `base_dir/.env` directly via `_load_dotenv_values()` — not via Settings — so tests with temp dirs work correctly
- Bootstrap manifest file: `bootstrap-manifest.json` (gitignored); re-run with `--force` to refresh
- New runtime directories created by setup (`cache/`, `models/`, `logs/`, `temp/`) are gitignored
- Test count: 1711 (1677 existing + 34 new bootstrap tests)

---

### 13. LOCAL_AI_MODEL_MANAGER (LAMM)
**Spec:** `docs/plug-and-play-setup/PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM_UPDATED.md`  
**Moved to `video_core` in Phase 0 (2026-07-12).** Originally `src/ytfactory/models/`; now `src/video_core/models/`.  
**New files:** `src/video_core/models/` package (8 modules), `config/models-registry.yaml`, `tests/test_local_ai_model_manager.py`  
**Modified:** `src/ytfactory/bootstrap/model_bootstrap.py`

#### Architecture
LAMM is the **single authority** for all local AI model lifecycle. No feature pipeline may download or manage models directly.

```
src/video_core/models/
├── __init__.py          # exports all types including BundleRuntime, FailureReason, ModelBundle, etc.
├── models.py            # ModelEntry, ModelState, ModelStatus, Backend, ProvisionResult + bundle types
├── registry.py          # load_registry() — reads config/models-registry.yaml via PyYAML
├── backend.py           # select_backend() — CUDA → MPS → CPU; describe_backend()
├── manifest.py          # model-manifest.json read/write (schema_version: "2")
├── manager.py           # LocalAIModelManager: provision(), validate_capabilities(), get_bundle()
├── capabilities.py      # validate_capabilities(), format_missing(), capability_error_message()
└── bundle.py            # BundleProvisioner, ContentAddressedCache, per-bundle locking, checksums
```

#### Model Registry (`config/models-registry.yaml`)
Three entries: `whisperx`, `silero_vad`, `minicpm_v2_6`. All have `auto_download: false` by default.
- Lazy models (`whisperx`, `silero_vad`): no `hf_repo` — skip download entirely; return VERIFIED immediately
- `minicpm_v2_6`: `hf_repo: "openbmb/MiniCPM-V-2_6"`, `min_disk_gb: 10`, requires torch/transformers/pillow

#### `LocalAIModelManager.provision()` logic
1. Check registry entry exists and is enabled
2. Check `requires_packages` — if any missing: return MISSING (warning, not error)
3. Check manifest — if VERIFIED and not force: return cached result
4. Select backend (CUDA→MPS→CPU per entry's `backends` list)
5. `has_repo = bool(entry.hf_repo)` — lazy models always route to `_verify_from_cache`
6. If `has_repo and (should_download or force)`: `_download_and_verify()` via `snapshot_download`
7. Otherwise: `_verify_from_cache()` — tries `try_to_load_from_cache()`; MISSING if not found

#### Key Invariants
- **Lazy models** (no `hf_repo`): `_verify_from_cache()` returns VERIFIED immediately — "downloads on first use"
- **`force=True` on lazy model** routes to `_verify_from_cache()`, NOT `_download_and_verify()` — prevents `snapshot_download("")` ValueError
- `ProvisionResult.ok` = True when status is VERIFIED, DOWNLOADED, or SKIPPED
- Model manifest: `models/model-manifest.json` at repo root (gitignored)
- Bootstrap now delegates all model checks to LAMM; the configured vision model (`qwen2_5_vl_3b` by default) is checked when `image_review_enabled=true`
- Test count: 30 new tests in `tests/test_local_ai_model_manager.py`

---

### 13a. MODEL_BUNDLE_ARCHITECTURE
**Spec:** `docs/video/MODEL_BUNDLE_ARCHITECTURE.md`  
**New files:** `src/video_core/models/capabilities.py`, `src/video_core/models/bundle.py`, `tests/test_model_bundle.py`  
**Modified:** `video_core/models/models.py`, `video_core/models/registry.py`, `video_core/models/manifest.py`, `video_core/models/manager.py`, `video_core/models/__init__.py`, `video_core/providers/vision/local.py`, `config/models-registry.yaml`

Every model is now a **bundle** of artifacts; LAMM owns the full lifecycle; providers declare capabilities; LAMM validates the capability contract before marking READY.

#### New types (`models/models.py`)
- `BundleRuntime`: `TRANSFORMERS` | `LLAMA_CPP` | `LAZY`
- `FailureReason`: `DOWNLOAD_FAILED` | `DISK_FULL` | `CHECKSUM_MISMATCH` | `INCOMPATIBLE_BUNDLE` | `MISSING_CAPABILITY` | `VALIDATION_TIMEOUT`
- `BundleArtifact(name, file, revision, checksum, compatible_with)` — single artifact
- `WarmInferenceConfig(sample_image, sample_prompt)` — post-download warm pass config
- `ModelBundle(runtime, artifacts, capabilities, warm_inference, auto_validate)` — artifact collection
- `ModelEntry` extended: `capabilities: list[str]`, `runtime: BundleRuntime`, `bundle: ModelBundle | None`
- `ModelState` / `ProvisionResult` extended: `capabilities`, `checksum_verified`, `bundle_artifacts`, `failure_reason`

All new fields have safe defaults — existing code unaffected (backward compatible).

#### Capability contract (`models/capabilities.py`)
`validate_capabilities(declared, required) → list[str]` — empty = all satisfied; non-empty = missing caps formatted as `MISSING_CAPABILITY(cap_name)`.

`LocalVisionProvider._load_model()` calls `manager.validate_capabilities(model_name, ["image_review"])` before loading — logs warning and returns None if missing (no error raised).

#### Bundle Provisioner (`models/bundle.py`)
- `get_bundle_lock(name)` — per-bundle `threading.Lock`; prevents concurrent duplicate provisioning
- `ContentAddressedCache`: GGUF artifacts at `{cache_dir}/{hex[:2]}/{hex}/{filename}`; LRU in `.lru.json`
- `verify_checksum(path, expected)` — accepts `"sha256:<hex>"` format
- `BundleProvisioner.provision()` dispatches to LAZY/TRANSFORMERS/LLAMA_CPP paths; records `bundle_artifacts`, `checksum_verified`, `failure_reason` in manifest

#### Registry + Manifest
Registry parses `runtime`, `capabilities`, `bundle.artifacts`, `bundle.warm_inference` per entry; synthetic minimal bundle created when no explicit `bundle:` section so `entry.bundle` is always non-None. Manifest writes `schema_version: "2"`; old manifests load with safe defaults.

#### `config/models-registry.yaml` additions
- `whisperx`, `silero_vad`: `runtime: lazy`, `capabilities: []`
- `minicpm_v2_6`: `runtime: transformers`, `capabilities: [image_review, structured_json]`, `bundle.artifacts.text_model: {file: "."}`

**Test count:** +72 new tests in `tests/test_model_bundle.py` → **1929 total**

---

### 14. IMAGE_REVIEW_PIPELINE_V1
**Spec:** `docs/video-quality-review/IMAGE_REVIEW_PIPELINE.md`  
**New files:** `src/video_core/providers/vision/` package (6 modules, incl. `llama_cpp_provider.py` added 07-12), `src/ytfactory/images/review_config.py`, `src/ytfactory/images/review_engine.py`, `src/ytfactory/images/review_models.py`, `src/ytfactory/review/validation/rules/vision_review.py`, `tests/test_vision_provider.py`, `tests/test_image_review_engine.py`  
**Moved to `video_core` in Phase 0 (2026-07-12).** Originally `src/ytfactory/providers/vision/`; now `src/video_core/providers/vision/`.  
**Modified:** `src/ytfactory/images/pipeline.py`, `src/ytfactory/config/settings.py`, `src/ytfactory/review/validation/runner.py`, `src/ytfactory/review/validation/config.py`

#### Vision Provider Abstraction
```
src/video_core/providers/vision/
├── __init__.py      # exports VisionProvider, VisionReviewResult, get_vision_provider
├── base.py          # VisionProvider ABC + VISION_REVIEW_PROMPT (6-category checklist)
├── models.py        # VisionReviewResult, VisionIssue, IssueSeverity
├── mock.py          # MockVisionProvider — default PASS, configurable fail_scenes
├── local.py         # LocalVisionProvider — lazy-loads via LAMM; MiniCPM-V 2.6 .chat() API
└── factory.py       # get_vision_provider("mock" | "local", local_model=...) → VisionProvider
```

ReviewPipeline is **completely model-agnostic** — VisionReviewValidator reads pre-written JSON artifacts, never imports vision model code.

#### `ImageReviewEngine.review_scene()` flow
1. Technical QA: file size ≥1000 bytes + OpenCV Laplacian sharpness ≥10.0 (optional, skipped if cv2 absent)
2. Vision provider review → `VisionReviewResult`
3. Pass criteria: `score≥90, confidence≥80, 0 HIGH issues, ≤1 MEDIUM issue`
4. PASS or SKIP/ERROR → stop
5. `auto_remediate=False` → stop (accept FAIL)
6. FAIL + more attempts remain → `_refine_prompt()` appends targeted corrections → `_regenerate()` → repeat

#### Prompt Refinement Rules (never rewrites — only appends)
| Issue category | Appended correction |
|---|---|
| anatomy/hand | "anatomically correct hands with exactly five fingers per hand" |
| face | "natural facial expression, symmetric face, realistic eyes" |
| artifact/watermark | "no watermarks, no text artifacts, no distortions" |
| lighting | "correct lighting direction, realistic shadows and highlights" |
| blur (medium) | "sharp focus, high detail, crisp edges" |
| proportion (medium) | "correct body proportions, natural posture" |
| (default) | "high quality, no artifacts, photorealistic, sharp focus" |

#### Workspace Artifacts
Per-scene (in `images/`): `image-review-NNN.json`, `image-remediation-NNN.json`, `image-review-prompt-NNN-A.txt` (when debug=true)
Global: `images/image-quality-summary.json` — aggregates PASS/FAIL/SKIP/ERROR counts + pass_rate

#### VisionReviewValidator (in ReviewPipeline)
Reads `images/image-quality-summary.json` — never calls any model. Four rules:
- `VIS_001` [warning]: summary file exists (SKIP all if absent)
- `VIS_002` [critical]: no scene with status FAIL
- `VIS_003` [medium]: all reviewed scenes above `vision_review_min_score` (default 90)
- `VIS_004` [low]: overall pass_rate ≥ `vision_review_min_pass_rate` (default 0.8)

#### Settings
```
IMAGE_REVIEW_ENABLED=true           # master switch (enabled by default)
VISION_REVIEW_PROVIDER=local        # "local" | "mock"
VISION_REVIEW_LOCAL_MODEL=qwen2_5_vl_3b
IMAGE_REVIEW_MIN_SCORE=90
IMAGE_REVIEW_CONFIDENCE=80
IMAGE_REVIEW_MAX_ATTEMPTS=3
IMAGE_REVIEW_AUTO_REMEDIATE=true
IMAGE_REVIEW_DEBUG=false
```

#### Key Invariants
- `image_review_enabled=true` (default) → `_build_review_engine()` creates vision engine at runtime
- Default local vision model is `qwen2_5_vl_3b` via **config only** — never hardcoded in business logic
- `_regenerate()` passes `seed=None` → new random seed each attempt
- ValidationRunner now runs 12 validators (was 10) — added VisionReviewValidator and CTAValidator
- Test count: 20 new (test_vision_provider.py) + 26 new (test_image_review_engine.py) = 46 new tests

---

## Image Prompt Engine Layers (order of application)

1. Shot planning — `images/shot_planner.py`
2. LLM visual prompt generation — `agents/nodes/scene_planner_node.py`
3. `enrich_for_provider()` in `images/prompt_engine.py`:
   - Human quality reinforcement (`human_detector.py`)
   - Subject dominance rule
   - Clothing & Cultural Authenticity policy (`clothing_policy.py`)
   - Provider anatomy reinforcement / negative prompts
4. `review_prompt()` — per-prompt validation
5. Diagnostics — `images/diagnostics.py`
6. HumanValidator in review pipeline — post-generation

---

## Key Invariants

- `scene-plan.json` is the central artifact — all downstream stages read `scenes[].visual_prompt`, `scenes[].narration`, `scenes[].duration_seconds`.
- `.gitignore` contains `build/` which matches `src/ytfactory/build/` — use `git add -f src/ytfactory/build/` when staging.
- **"human" NOT in `_HUMAN_INDICATORS`** — false positive with "natural human anatomy".
- Locked scenes NEVER auto-regenerated.
- `RemediationAction` requires `confidence: int` and `rationale: str` fields (not optional).
- `kokoro` and `whisperx` are lazy-imported — not in `pyproject.toml`. Must be installed manually.
- Gemini providers (`llm/gemini.py`, `image/gemini.py`) now raise a clear `ValueError` if `GEMINI_API_KEY` is empty, with a message pointing to `.env` and CWD.
- Running `uv run ytfactory` from a wrong directory silently skips `.env` → Settings defaults (`llm_provider="anthropic"`) → crash with empty key. Always run from repo root.
- `get_brand_config()` is a singleton — call `reset_brand_config_cache()` in any test that swaps the brand config file.
- **Domain model split (Phase 0):** Generic provider I/O shapes (`LLMResponse`, `SearchResult`, `ImageRequest`) live in `src/video_core/domain/`. Factory-specific models (`Project` + stage-status dict, audio/scene/video models) stay in `src/ytfactory/domain/`. `ProjectRepository` (`storage/project_repository.py`) is unchanged — still factory-owned.
- **Settings split (Phase 1):** `ytfactory.config.Settings` now inherits `video_core.config.SharedSettings`. Shared fields (API keys, provider selectors, model names, kokoro/a1111 provider config, `tts_auto_retry/max_retries`) live in `SharedSettings`; pipeline/quality/content fields stay in `Settings`. All existing `settings.<field>` call sites are unchanged. Both classes load from the same `.env` file — no `.env` change needed. One remaining Bucket-C layering exception: `ytfactory.shared.constants` (WORKSPACE_DIR, tracked for Phase 2).
- **No feature pipeline may download/manage models directly** — all model lifecycle routes through `LocalAIModelManager` (LAMM).
- `force=True` on a lazy model (no `hf_repo`) routes to `_verify_from_cache()`, NOT `_download_and_verify()` — prevents `snapshot_download("")` ValueError.
- **Capability contract:** call `manager.validate_capabilities(model_name, required)` before loading. Returns `[]` on success; non-empty means `MISSING_CAPABILITY(cap)` — treat as pre-condition failure.
- **`entry.bundle` is always non-None after registry parse** — `_parse_bundle()` creates a synthetic minimal bundle when no explicit `bundle:` section exists.
- **Dockerfile uses `COPY config/ config/`** — `models-registry.yaml` and `brand_config.yaml` are baked in at `/app/config/`. Never use `COPY brand_config.yaml*` from root (that file doesn't exist; `config/` is the canonical location).
- **`model_bootstrap.py` uses `_get_vision_model_name()`** to look up the configured vision model key from Settings — not hardcoded `"minicpm_v2_6"`.
- **ValidationRunner runs 12 validators** (Sections: script, narration, subtitle, image, human, motion, audio, rendering, story, bgm, vision_review, cta).

---

## Workspace Layout

```
workspace/jobs/<project-id>/
├── project.json
├── research/         research.md, research.json, sources.json
├── script/           script.md
├── scenes/           scene-plan.json, scene-status.json
├── images/           scene-001.png … manifest.json, image-quality-summary.json, image-review-NNN.json, image-remediation-NNN.json
├── audio/            scene-001.mp3, .timing.json, .alignment.json
├── subtitles/        scene-001.srt, .ass
├── video/            scene-001.mp4 … final.mp4
├── review/           17+ review output files
├── remediation/      4 files
├── publish/          10 files (includes pinned-comment.txt)
└── bgm-debug/        5 files (written when BGM_VAD_ENABLED=true): speech_timeline.json, ducking_events.json, mix_profile.json, ffmpeg_filter.txt, audio_levels.csv
```

---

## Test Patterns

```bash
uv run pytest tests/          # run all safe tests (no live API)
uv run pytest tests/ -k "keyword"
```

When patching `WORKSPACE_DIR`:
```python
monkeypatch.setattr("ytfactory.review.engine.WORKSPACE_DIR", str(tmp_path))
monkeypatch.setattr("ytfactory.review.artifacts.WORKSPACE_DIR", str(tmp_path))
```

When patching Settings for lazy imports inside executor methods:
```python
patch("ytfactory.config.settings.Settings", ...)   # correct
# NOT "ytfactory.review.remediation.executor.Settings"  ← wrong
```

For VoicePipeline tests requiring CWD to resolve `workspace/`:
```python
import os
orig = os.getcwd()
os.chdir(tmp_path)   # actual chdir BEFORE entering patch context managers
try:
    with patch(...):
        pipeline.run(project_id)
finally:
    os.chdir(orig)
```
