# YouTube Factory — End-to-End Architecture Audit

**Date:** 2026-07-10
**Reference:** `docs/context/MASTER_CONTEXT.md`
**Test count at audit time:** 2124 passing
**Auditor:** Claude Sonnet 4.6 via parallel agent inspection

---

## 1. End-to-End Pipeline Diagram

```
╔══════════════════════════════════════════════════════════════════════╗
║              TWO EXECUTION PATHS                                     ║
╠══════════════════════════════════════════════════════════════════════╣
║  PATH A: Agentic  ytfactory run <topic>                             ║
║  PATH B: Sequential  ytfactory build <id>  /  manual CLI commands   ║
╚══════════════════════════════════════════════════════════════════════╝

PATH A — LangGraph graph (agents/graph.py)
──────────────────────────────────────────
[topic given]                     [script_md in state]
       │                                   │
       ▼                                   ▼
 research_agent ──────────────→ script_enhancer ──────┐
       │                                              │
       ▼                                              │
 script_writer                                        │
       │                                              │
       ▼                                              │
 human_review_script                                  │
       │                                              │
       └──────────────────────────┬───────────────────┘
                                  ▼
                            scene_planner
                                  │
                                  ▼
                         human_review_scenes
                                  │
                    ┌─────────────┴─────────────┐
                    │ _dispatch_scenes (Send/fan-out)
                    │  one call per scene
                    ▼
           generate_scene_assets  [image + voice + captions per scene]
                    │
                    ▼  (all scenes merged via state reducers)
             video_renderer  [per-scene .mp4, MotionPlanner]
                    │
                    ▼
          video_concatenator  [final.mp4 via compose_continuous_video() + BGM]
                    │
                    ▼
            quality_review  [ReviewPipeline.run()]
                    │
          ┌─────────┴──────────┐
         PASS                FAIL
          │                   │
          ▼                   ▼
       publish          remediation  [AutoRemediationEngine]
          │                   │
          ▼                PASS/FAIL
         END                  │
                              ▼
                           publish / END
          ⚠ NO CTA NODE — CTA overlay NEVER applied in agentic path

PATH B — BuildPipeline (build/pipeline.py)
──────────────────────────────────────────
  [scenes]
     ↓  ScenePipeline         reads: script/script.md
        writes: scenes/scene-plan.json
     ↓  ImagePipeline          reads: scenes/scene-plan.json
        [ImageRemediationOrchestrator embedded per-scene]
           ↓ [per scene loop]
              ImageProvider.generate()  → scene-NNN.png
              Human sharpness retry loop (up to image_human_max_retries)
              ImageRemediationOrchestrator.review_scene()
                → ImageReviewEngine (single-shot)
                → if FAIL: PromptRemediationBuilder.build()
                → ImageProvider.generate() [refined prompt]
                → repeat up to image_review_max_attempts
              writes: images/remediation/scene-NNN/attempt-N/{prompt.md,review.json}
              writes: images/remediation/scene-NNN/final/{review.json,metadata.json}
        writes: images/scene-NNN.png, images/manifest.json,
                images/image-quality-summary.json
     ↓  VoicePipeline          reads: scenes/scene-plan.json
        writes: audio/scene-NNN.mp3, .timing.json, .alignment.json (optional)
     ↓  CaptionPipeline        reads: scenes, audio/
        writes: subtitles/scene-NNN.srt, .ass
     ↓  VideoPipeline          reads: images/, audio/, subtitles/
        [MotionPlanner, TransitionPlanner, EffectsPlanner, FFmpegRenderer]
        [_apply_bgm() → BGMLibrary + BGMMixer embedded here]
        writes: video/scene-NNN.mp4, video/final.mp4
     ↓  CTAPipeline            reads: video/final.mp4
        writes: cta/cta-timing.json, video/final.pre-cta.mp4 (backup)
     ↓  ReviewPipeline         reads: all workspace artifacts
        [VideoQualityReviewEngine → 12 validators → RCA → Scoring → EFL]
        writes: review/ (17+ files)
     ↓  [if FAIL] AutoRemediationEngine
        writes: remediation/ (4 files)
     ↓  PublishPipeline        reads: scenes/, script/, audio/
        [Chapters, Title, SEO, Description, PinnedComment, Thumbnail, UploadPackage]
        writes: publish/ (11 files incl. pinned-comment.txt)
```

---

## 2. Component Interaction Diagram

```
CLI (cli/main.py)
 ├── BuildPipeline ──────────────────────────────────────────────────┐
 │    ├── ScenePipeline → GeminiScenePlanner → get_llm_provider()   │
 │    ├── ImagePipeline → get_image_provider()                       │
 │    │    ├── [human retry] compute_sharpness / ImageProvider       │
 │    │    └── ImageRemediationOrchestrator                          │
 │    │         ├── ImageReviewEngine (single-shot)                  │
 │    │         │    └── get_vision_provider() → LocalVisionProvider │
 │    │         │         └── LAMM → validate_capabilities()         │
 │    │         └── PromptRemediationBuilder                         │
 │    ├── VoicePipeline → get_tts_provider() → KokoroProvider        │
 │    │    └── [whisperx] WhisperXAligner (optional)                 │
 │    ├── CaptionPipeline → SubtitleEngine                           │
 │    │    └── [optional] SubtitleEditingEngine (LLM)                │
 │    ├── VideoPipeline                                              │
 │    │    ├── FFmpegRenderer                                        │
 │    │    ├── MotionPlanner / TransitionPlanner / EffectsPlanner    │
 │    │    └── _apply_bgm() → BGMMixer → BGMLibrary + VAD           │
 │    ├── CTAPipeline → CTAPlacementEngine → CTARenderer             │
 │    ├── ReviewPipeline → VideoQualityReviewEngine                  │
 │    │    └── ValidationRunner (12 validators)                      │
 │    │         ├── VisionReviewValidator (reads image-quality-summary.json)
 │    │         ├── HumanValidator                                   │
 │    │         ├── BGMValidator (BGM_005–010)                       │
 │    │         └── CTAValidator                                     │
 │    ├── [if FAIL] AutoRemediationEngine → ProductionExecutor       │
 │    └── PublishPipeline → LLM + ImageProvider                     │
 │         ├── ChaptersGenerator                                     │
 │         ├── TitleGenerator                                        │
 │         ├── SEOGenerator                                          │
 │         ├── DescriptionGenerator                                  │
 │         ├── PinnedCommentGenerator                                │
 │         ├── ThumbnailGenerator                                    │
 │         └── UploadPackageGenerator (→ package.py)                │
 │                                                                    │
 └── IncrementalBuildEngine → SHA-256 manifest → stage invalidation │

Providers (factory pattern)
 ├── LLM: get_llm_provider() → gemini|groq|ollama|anthropic(→OpenAI)
 ├── Image: get_image_provider() → pollinations|huggingface|gemini|a1111
 ├── TTS: get_tts_provider() → edge|kokoro|[elevenlabs: blocked]
 ├── Vision: get_vision_provider(name, model) → mock|local(→LAMM)
 └── Search: get_search_provider() → tavily

LAMM (models/)
 ├── LocalAIModelManager.provision() → lazy|download|verify
 ├── BundleProvisioner → ContentAddressedCache
 ├── validate_capabilities()
 └── Registry: models-registry.yaml (whisperx, silero_vad, minicpm_v2_6, qwen2_5_vl_3b)
```

---

## 3. Data Flow Diagram

```
topic/script.txt
      │
      ▼
project.json  (create)
      │
      ▼
script/script.md  (import-script OR research+script_writer)
      │
      ▼ [MISSING IN SEQUENTIAL: no script refinement step]
      │
scenes/scene-plan.json  ←── CENTRAL ARTIFACT
      │
      ├──────────────────────────────────────────────────┐
      ▼                                                  ▼
images/scene-NNN.png                        audio/scene-NNN.mp3
[image-quality-summary.json]               [.timing.json]
[image-review-NNN.json]                    [.alignment.json]  ←── WhisperX (optional)
[image-remediation-NNN.json]                     │
      │                                          ▼
      │                               subtitles/scene-NNN.srt
      │                               subtitles/scene-NNN.ass
      │                                          │
      └──────────────────┬───────────────────────┘
                         ▼
               video/scene-NNN.mp4  (per-scene clip)
                         │
               video/final.mp4  ←── BGM mixed inside VideoPipeline
               [video/final.pre-cta.mp4  (backup after CTA)]
               bgm-debug/ (speech_timeline.json, state_timeline.json, etc.)
                         │
                         ▼ CTA overlay
               video/final.mp4  (modified)
               cta/cta-timing.json
                         │
                         ▼
               review/  (17+ files)
               remediation/  (4 files)
                         │
                         ▼
               publish/
                 ├── thumbnail.png + thumbnail-variants/
                 ├── title.txt, alternate-titles.txt
                 ├── description.md
                 ├── keywords.txt, hashtags.txt, youtube-tags.txt
                 ├── chapters.txt
                 ├── pinned-comment.txt
                 └── youtube-metadata.json
```

---

## 4. Missing Wiring Report

### MW-001 [HIGH] — CTA absent from agentic path

`ytfactory run` (LangGraph graph) never applies CTA overlay.

`graph.py` has no `cta` node. The graph goes: `video_concatenator → quality_review → publish`. `CTAPipeline` is never instantiated or called in the agentic path.

**Impact:** Any video produced via `ytfactory run` will have no CTA overlay regardless of config. The `quality_review` node runs `ReviewPipeline` which instantiates `CTAValidator` — but there is no CTA artifact to validate, so CTA checks SKIP.

**Affected modules:** `agents/graph.py`, `agents/nodes/`, `cta/pipeline.py`

---

### MW-002 [HIGH] — Script Refinement absent from sequential path

`ytfactory build` has no script enhancement stage.

In the agentic path, `script_enhancer_node` rewrites/enhances a user-supplied script before scene planning. In `BuildPipeline`, there is no equivalent — it reads `script.md` directly and plans scenes immediately. Brand structure enforcement (hook → welcome → teaching → reflection → signature → CTA → quote) only happens in the agentic path via `script_writer_node` and `script_enhancer_node`. Manual `import-script` + `plan-scenes` bypasses all script quality enforcement.

**Impact:** Scripts imported via `import-script` and built via `build` never get Brand Template System enforcement or script quality improvements before scene planning.

**Affected modules:** `build/pipeline.py`, `import_script/`, `scenes/pipeline.py`

---

### MW-003 [MEDIUM] — BGM not independently controllable in sequential incremental build

`"bgm"` is not a stage in `PIPELINE_STAGES`.

`FORCE_FLAG_TO_STAGE["bgm"] = "video"` exists so `--force-bgm` invalidates the video stage, but BGM is fully embedded in `VideoPipeline._apply_bgm()`. There is no way to re-run only BGM on an existing `final.mp4` via incremental mode (only `ytfactory mix-bgm` does this, via the standalone `BGMPipeline`). The `BGMPipeline` class is documented as standalone/testing only — `BuildPipeline` never instantiates it.

**Impact:** Changing BGM settings forces full video re-render.

---

### MW-004 [LOW] — Research not chained in BuildPipeline

By design — documented in CLAUDE.md. `ResearchPipeline` is a standalone CLI-only step. `BuildPipeline` starts at `scenes`. No gap relative to the stated design.

---

## 5. Broken Integration Report

### BI-001 [HIGH] — ScenePipeline hardcodes `GeminiScenePlanner` by name

```python
# scenes/pipeline.py
from ytfactory.scenes.planner.gemini_planner import GeminiScenePlanner
class ScenePipeline:
    def __init__(self, settings: Settings):
        self._planner = GeminiScenePlanner(settings)
```

`GeminiScenePlanner` internally calls `get_llm_provider(settings)` correctly, so the LLM is provider-agnostic at runtime. But the class name is `GeminiScenePlanner` and only one planner exists. If `LLM_PROVIDER=anthropic`, the planner still works (delegates to `OpenAICompatibleProvider`), but the class name violates the provider-agnostic naming invariant stated in the master context.

**Affected:** `scenes/pipeline.py`, `scenes/planner/gemini_planner.py`

---

### BI-002 [MEDIUM] — LLM factory error message omits `anthropic`

```python
# providers/llm/factory.py ~line 33
raise ValueError("... Valid options: gemini, groq, ollama")
```

`"anthropic"` is a valid and currently-active provider (the `.env` uses it). A typo in the provider name produces a misleading error.

**Affected:** `providers/llm/factory.py`

---

### BI-003 [MEDIUM] — ElevenLabs raises `NotImplementedError`, not `ValueError`

```python
# providers/tts/factory.py
case "elevenlabs":
    raise NotImplementedError("ElevenLabs not implemented. Use TTS_PROVIDER=edge")
```

CLAUDE.md lists ElevenLabs as a valid TTS option. A stub `elevenlabs.py` file exists in the providers directory. The factory explicitly blocks it. Users expecting `TTS_PROVIDER=elevenlabs` to work get a `NotImplementedError`.

**Affected:** `providers/tts/factory.py`, `providers/tts/elevenlabs.py`

---

### BI-004 [LOW] — `CaptionPipeline.run()` and `VideoPipeline.run()` use `project` not `project_id`

Both pipelines define `def run(self, project: str)` but are called positionally (`self.captions.run(project_id)`) — Python passes by position so it works, but any keyword-argument call (`self.captions.run(project_id=x)`) would fail. Inconsistent with all other pipeline signatures.

**Affected:** `captions/pipeline.py:39`, `video/pipeline.py:250`

---

### BI-005 [LOW] — `publish_node` in agentic path calls `PublishPipeline(config=config)` without settings

The agentic publish node constructs `PublishPipeline(config=config)` — no `settings=` passed. `PublishPipeline.__init__` defaults to `settings or Settings()`, which constructs a new `Settings()` from `.env`. This works in production but diverges from `BuildPipeline` which passes the shared `settings` instance.

**Affected:** `agents/nodes/publish.py:25–27`

---

## 6. Architectural Smells

### AS-001 — BGM exists in both `BGMPipeline` and `VideoPipeline._apply_bgm()`

`BGMPipeline.run()` exists with a documented note: *"BGM is NOT applied via this class in the build pipeline."* The CLI `mix-bgm` correctly uses `BGMPipeline`. `BuildPipeline` and the agentic `video_concatenator_node` both call `compose_continuous_video()` which embeds BGM internally. Two code paths for the same operation — if BGM V3 parameters change in `BGMConfig`, they must be verified in both paths.

### AS-002 — `video_renderer_node` duplicates planning logic from `VideoPipeline`

Both `video_renderer_node` (agentic) and `VideoPipeline` (sequential) instantiate `MotionPlanner`, `TransitionPlanner`, `EffectsPlanner`. Both code paths must be kept in sync when the cinematic engine changes.

### AS-003 — `GeminiScenePlanner` is misnamed — it is actually a generic LLM scene planner

The concrete provider is selected at runtime via `get_llm_provider(settings)`. The class should be `LLMScenePlanner` or `ScenePlanner` to honour the provider-agnostic invariant stated in the master context.

### AS-004 — ValidationRunner stale docstrings create confusion about validator count

| Location | States |
|---|---|
| Module docstring line 1 | "orchestrates all **11** category validators" |
| `run()` method docstring line 42 | "Run all **8** validators" |
| Actual instantiated validators | **12** (confirmed via source) |
| Master context | **11** (also out of date — missing CTAValidator) |

### AS-005 — `ImageReviewConfig` type inconsistency

```python
# settings.py
image_review_min_score: int = 90
image_review_confidence: int = 80
# review_config.py
min_score: float = 90.0
min_confidence: float = 80.0
```

`ImageReviewConfig.from_settings()` casts them via `float(getattr(settings, ...))` — works but creates an implicit conversion between annotated `int` and used `float`.

### AS-006 — PublishPipeline progress labels are stale

Steps 1–4 print `[1/6]` through `[4/6]`; steps 5–7 print `[5/7]` through `[7/7]`. `PinnedCommentGenerator` was added as step 5 but the labels before it were not updated to `/7`.

---

## 7. Dead Code Report

### DC-001 — `BGMPipeline` class is not used by any pipeline or build path

`src/ytfactory/bgm/pipeline.py` exists and is used only by the `mix-bgm` CLI command. The module docstring explicitly states it is not used by the build pipeline. It is functionally alive (for `ytfactory mix-bgm`) but structurally disconnected from `BuildPipeline`.

**Status:** Intentionally standalone — not dead, but the dual-existence creates confusion.

### DC-002 — `providers/tts/elevenlabs.py` stub is unreachable

The TTS factory raises `NotImplementedError` before instantiating `ElevenLabsProvider`. The file exists but can never be reached via the factory.

### DC-003 — `silero_vad` model entry in registry has no consumer in production code

`config/models-registry.yaml` defines a `silero_vad` entry, but the BGM VAD implementation uses FFmpeg `silencedetect` (not Silero). `BGMConfig.vad_provider = "silero"` is set in settings but `detect_speech()` in `vad.py` uses `silencedetect`. No production code path calls `LocalAIModelManager.provision("silero_vad")`. The registry entry is speculative/reserved.

---

## 8. Configuration Inconsistencies

| # | Setting | Settings Default | Master Context / CLAUDE.md | Impact |
|---|---|---|---|---|
| CI-001 | `image_provider` | `"pollinations"` | `"huggingface"` (CLAUDE.md example) | Fresh install with no `.env` uses Pollinations, not FLUX |
| CI-002 | `image_width` / `image_height` | `1920×1080` | `1280×720` (master context current stack) | Image resolution mismatch from code default vs documented env |
| CI-003 | `bgm_enabled` | `False` | `true` (master context BGM_ENABLED) | BGM disabled by default in code |
| CI-004 | `whisperx_enabled` | `False` | `true` (master context WHISPERX_ENABLED) | WhisperX disabled by default |
| CI-005 | `subtitle_editor_enabled` | `False` | `false` (matches) | OK |
| CI-006 | `kokoro_speed` | `1.0` | `0.85` (master context KOKORO_SPEED) | Contemplative pacing speed not reflected in code default |
| CI-007 | `tts_pacing_enabled` | `True` | `true` (matches) | OK |
| CI-008 | `image_review_enabled` | `False` | not set in master context `.env` table | OK — off by default is correct |

CI-001 through CI-006 are all code defaults vs documented `.env` values. The actual running system uses `.env` values which override code defaults. This is not a bug but any fresh install without a pre-configured `.env` will behave differently than documented.

---

## 9. Provider Inconsistencies

| # | Provider | Factory | Status | Issue |
|---|---|---|---|---|
| PI-001 | LLM/anthropic | `OpenAICompatibleProvider` | Working | Class name misleads — not Anthropic SDK native |
| PI-002 | LLM factory error | `get_llm_provider()` | Misleading | Error message omits `"anthropic"` from valid options |
| PI-003 | TTS/elevenlabs | `NotImplementedError` | Blocked | Documented as valid option in CLAUDE.md |
| PI-004 | Vision factory | `get_vision_provider(name, model)` | Works | Different signature from all other factories (takes name+model, not Settings) |
| PI-005 | Search | Only Tavily | Working | Single provider — factory pattern asymmetric but harmless |
| PI-006 | Image default | Pollinations | Works | Not documented in master context as a supported provider |

---

## 10. Registry Inconsistencies

| # | Entry | Issue |
|---|---|---|
| RI-001 | `silero_vad` | Present in YAML but missing from `_builtin_defaults()` in `registry.py` — if PyYAML is absent, silero_vad has no fallback. Only `whisperx` and `minicpm_v2_6` are hardcoded fallbacks. |
| RI-002 | `qwen2_5_vl_3b` | Present in YAML; master context memory references it as a valid alternative vision model — consistent. |
| RI-003 | `minicpm_v2_6` | Present and correct. Synthetic minimal bundle created when no explicit `bundle:` section — `entry.bundle` always non-None. |
| RI-004 | `silero_vad` | `capabilities: []` — expected; no production consumer exists. |

---

## 11. Retry Flow Validation

| Stage | Retry? | Mechanism | Max | Config key |
|---|---|---|---|---|
| Research | No | — | — | — |
| ScenePlanning | No | — | — | — |
| ImageGeneration (human sharpness) | Yes | sharpness loop | `image_human_max_retries=2` | `image_human_max_retries` |
| ImageRemediation (orchestrator) | Yes | FAIL→refine→regenerate | `image_review_max_attempts=3` | `image_review_max_attempts` |
| ImageReviewEngine (internal) | Single-shot | `max_attempts=1, auto_remediate=False` set by orchestrator | 1 | n/a |
| VoicePipeline | Yes | Exponential backoff (base 2s, doubles each attempt) | `tts_max_retries=3` | `tts_max_retries` |
| SubtitleEditingEngine | Yes | Multi-pass quality loop | `subtitle_editor_max_passes=3` | `subtitle_editor_max_passes` |
| CTA rendering | Yes | 3-step escalation | **3 (hardcoded)** | **None — not configurable** |
| Post-render AutoRemediation | Yes | re-validate loop | `remediation_max_retries=3` | `RemediationConfig.max_retries` |
| BGM mixing | Fail-soft | Non-fatal on exception | 0 (best-effort) | — |
| Publish generators | Fail-safe | `_parse_json_response()` fallback | 0 | — |

**Retry gap:** CTA retry count is hardcoded to 3 steps — not configurable via `Settings`. Every other retry is settings-driven. This is the only exception.

---

## 12. Production Readiness Score

| Subsystem | Score | Rationale |
|---|---|---|
| Sequential pipeline (`build`) | 94/100 | CTA present, BGM wired, image review embedded |
| Agentic pipeline (`run`) | 78/100 | CTA missing, script refinement path differs |
| Provider abstraction | 88/100 | ElevenLabs blocked, Gemini planner name, error message gap |
| Image review & remediation | 97/100 | Fully wired, all files written correctly |
| BGM V3 adaptive mixing | 96/100 | All features present, embedded in video stage |
| Review pipeline (12 validators) | 95/100 | Stale docstrings only |
| Post-render remediation | 95/100 | Full loop implemented |
| Publish package (all 11 files) | 97/100 | Pinned comment present |
| LAMM + Model Registry | 93/100 | silero_vad fallback gap |
| CLI commands | 99/100 | All commands registered |
| Configuration coverage | 88/100 | Code defaults differ from documented `.env` |
| Incremental build | 92/100 | bgm not a named stage |
| **OVERALL** | **91/100** | |

**Verdict:** The system CAN autonomously generate a complete production-quality YouTube video via `ytfactory build` without missing wiring or unintended manual intervention (except documented `MANUAL_REVIEW` fallbacks). The sequential path is production-ready. The agentic path (`ytfactory run`) has a critical gap: CTA is never applied.

---

## Implementation Checklist — Ordered by Priority

### P1 — Critical (blocks production for agentic users)

**[P1-A] Wire CTA into the agentic LangGraph path**

- **Why:** Any video produced via `ytfactory run` has no CTA overlay applied — a documented production feature is silently skipped.
- **Affected:** `agents/graph.py`, new `agents/nodes/cta.py`
- **Impact:** All agentic-path videos missing CTA
- **Fix:** Add a `cta` node between `video_concatenator` and `quality_review`. Node calls `CTAPipeline().run(project_id)`. Wire: `video_concatenator → cta → quality_review`.

**[P1-B] Add script refinement to sequential path**

- **Why:** `ytfactory build` skips brand structure enforcement and script quality checks that are only in the agentic `script_enhancer_node`.
- **Affected:** `build/pipeline.py`, new `ScriptEnhancerPipeline` or reuse existing node logic
- **Impact:** Brand Template System V1 is only enforced in the agentic path
- **Fix:** Extract `script_enhancer_node` logic into a callable `ScriptEnhancerPipeline`. Call it in `BuildPipeline` after `import-script` and before `ScenePipeline`. Gate behind `--skip-script-enhance` flag for users who want raw script passthrough.

---

### P2 — High (documentation/discovery failure, not runtime failure)

**[P2-A] Fix LLM factory error message to include `"anthropic"`**

- **File:** `providers/llm/factory.py:33`
- **Fix:** `"Valid options: gemini, groq, ollama, anthropic"`

**[P2-B] Update all stale ValidationRunner docstrings**

- **File:** `review/validation/runner.py:1` and `runner.py:42`
- **Fix:** Line 1: "orchestrates all **12** category validators". Line 42: "Run all **12** validators".
- Also update `MASTER_CONTEXT.md`: "ValidationRunner now runs **12** validators (was 11)".

**[P2-C] Rename `GeminiScenePlanner` to `LLMScenePlanner`**

- **Files:** `scenes/planner/gemini_planner.py`, `scenes/pipeline.py`
- **Why:** Violates provider-agnostic naming invariant. Using `LLM_PROVIDER=anthropic` still routes through a class called `GeminiScenePlanner`.
- **Fix:** Rename class and file. Update import in `scenes/pipeline.py`.

---

### P3 — Medium (configuration/behaviour divergence)

**[P3-A] Fix `CaptionPipeline.run()` and `VideoPipeline.run()` parameter name**

- Both use `project` instead of `project_id`
- **Files:** `captions/pipeline.py:39`, `video/pipeline.py:250`
- **Fix:** Rename parameter to `project_id` for consistency. All callers pass positionally so rename is safe.

**[P3-B] Implement or formally remove ElevenLabs TTS**

- **File:** `providers/tts/factory.py`, `providers/tts/elevenlabs.py`
- **Fix option A:** Implement `ElevenLabsProvider` fully.
- **Fix option B:** Remove `elevenlabs.py` stub and change `NotImplementedError` to `ValueError("ElevenLabs not implemented. Valid options: edge, kokoro")`.

**[P3-C] Add `silero_vad` to `_builtin_defaults()` in `registry.py`**

- **File:** `models/registry.py`
- **Why:** If PyYAML is absent, silero_vad has no fallback. The BGM VAD pipeline references it in settings.
- **Fix:** Add lazy entry to `_builtin_defaults()` matching the YAML entry.

**[P3-D] Fix `publish_node` to pass shared settings**

- **File:** `agents/nodes/publish.py:25`
- **Fix:** Cache `Settings()` at module scope (as `video_renderer_node` does) and pass it: `PublishPipeline(config=config, settings=_settings)`.

---

### P4 — Low (cosmetic, documentation)

**[P4-A] Fix publish pipeline progress labels**
Update `[1/6]`–`[4/6]` to `[1/7]`–`[4/7]` in `publish/pipeline.py`.

**[P4-B] Fix `ImageReviewConfig` type inconsistency**
Change `image_review_min_score: int = 90` and `image_review_confidence: int = 80` to `float` in `settings.py`, or remove the explicit `float()` cast in `review_config.py`.

**[P4-C] Fix `ImagePromptEngineV4` vs V5 docstring**
Align class name and module docstring version marker.

**[P4-D] Update `MASTER_CONTEXT.md`**
Correct validator count from 11 → 12 (CTAValidator was added). Update test count to 2124.

**[P4-E] Document `BGMPipeline` scope in CLI help**
The `mix-bgm` CLI help text should note that this is the standalone re-apply path (BGM is normally embedded in `ytfactory render`/`build`).

**[P4-F] Make CTA retry count configurable via Settings**
Add `cta_max_retries: int = 3` to `settings.py`. Thread it through `CTAPipeline` so CTA is consistent with every other retry policy.

---

## Summary Matrix

| Check | Result |
|---|---|
| Sequential pipeline complete? | ✅ Yes (scenes → images → voice → captions → video+BGM → CTA → review → remediate → publish) |
| Agentic pipeline CTA? | ❌ Missing — CTA node absent from graph |
| Image review + orchestrator wired? | ✅ Yes — embedded in ImagePipeline per-scene |
| PromptRemediationBuilder wired? | ✅ Yes — called by ImageRemediationOrchestrator |
| BGM V3 adaptive mixing wired? | ✅ Yes — BGMConfig, BGMMixer, BGMDebugWriter all V3 |
| BGM Kokoro timeline source? | ✅ Yes — `build_speech_timeline_from_kokoro()` exists |
| 4-level BGMLibrary fallback? | ✅ Yes — confirmed |
| Publish pinned-comment.txt? | ✅ Yes — PinnedCommentGenerator + UploadPackageGenerator |
| ValidationRunner validator count? | ⚠ 12 actual (master context says 11, stale docstrings say 8) |
| LAMM provision() lazy model path? | ✅ Yes — force=True on lazy → `_verify_from_cache` |
| LAMM silero_vad fallback? | ⚠ Missing from `_builtin_defaults()` |
| All 12 PromptRemediationBuilder rules? | ✅ Yes |
| `_RULE_DETECTORS` 12 entries? | ✅ Yes |
| ScenePipeline provider-agnostic? | ⚠ Class named `GeminiScenePlanner` but delegates to `get_llm_provider()` |
| Script refinement in sequential path? | ❌ Missing |
| All CLI commands registered? | ✅ Yes (all 24+ confirmed) |
| Dead code? | ⚠ BGMPipeline (intentional standalone), `elevenlabs.py` stub, `silero_vad` registry entry |
| No duplicate logic? | ⚠ BGM exists in both `VideoPipeline._apply_bgm()` and `BGMPipeline` |
| CTA retry configurable? | ⚠ Hardcoded to 3 steps |
