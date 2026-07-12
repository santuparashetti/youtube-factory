# Architecture Audit — 2026-07-12 (Incremental)

**Baseline:** `ARCHITECTURE_AUDIT_2026_07_10.md`
**Diff scope:** 144 files changed, 16 550 insertions / 1 341 deletions since commit `22be1e6` (first commit after 2026-07-10)
**Test count:** 2156 passing, 3 failing (was 2124 passing, 0 failing)

Key new modules introduced since last audit:
`benchmark/` · `script_enhancer/pipeline.py` · `workflow/image_remediation_orchestrator.py` ·
`providers/vision/llama_cpp_provider.py` · `scenes/planner/llm_planner.py` ·
`review/validation/rules/cta.py` · `agents/nodes/cta.py` · `prompts/prompt_remediation_builder.py`

---

## Resolved Since Last Audit

| ID | Description | Resolved by |
|---|---|---|
| MW-001 | CTA absent from agentic path | `agents/graph.py`: `cta_node` added between `video_concatenator` and `quality_review`; `agents/nodes/cta.py` created |
| MW-002 | Script refinement absent from sequential `build` path | `build/pipeline.py`: `ScriptEnhancerPipeline` imported and called in `run()` before `ScenePipeline` |
| MW-005 | `run_incremental()` skipped `ScriptEnhancerPipeline` | `build/pipeline.py`: `script` stage check added before `scenes` in `run_incremental()`; 2 tests added to `test_incremental.py` (dirty → called, clean → skipped) |
| BI-001 | `ScenePipeline` hardcoded `GeminiScenePlanner` by name | `scenes/planner/llm_planner.py` created; `scenes/pipeline.py` now imports `LLMScenePlanner`; `gemini_planner.py` kept as a backward-compat re-export alias (`LLMScenePlanner as GeminiScenePlanner`) |
| AS-003 | `GeminiScenePlanner` alias file dead (no consumers) | `scenes/planner/gemini_planner.py` deleted; zero import references confirmed before delete |
| BI-003 / DC-002 | ElevenLabs stub unreachable | `video_core/providers/tts/elevenlabs.py` deleted; factory's `ValueError("ElevenLabs TTS is not implemented")` retained as the correct signal |
| BI-002 | LLM factory error message omitted `anthropic` | `providers/llm/factory.py:33` — error now lists `gemini, groq, ollama, anthropic` |
| BI-004 | `CaptionPipeline.run()` / `VideoPipeline.run()` param named `project` not `project_id` | Both pipelines now declare `project_id: str`; all callers updated |
| BI-005 | `publish_node` constructed `Settings()` per-call instead of sharing | `agents/nodes/publish.py`: module-level `_settings = Settings()`, passed as `settings=_settings` to `PublishPipeline` |
| AS-004 | ValidationRunner docstrings said 11 / 8 validators (actual: 12) | `review/validation/runner.py:1` and `:42` both now read "12 category validators" |
| AS-005 | `image_review_min_score` / `image_review_confidence` typed `int` in `settings.py`, `float` in `review_config.py` | `settings.py:419,422` now declare both as `float` — no implicit cast needed |
| AS-006 | PublishPipeline progress labels stuck at `/6` (7 generators since PinnedComment added) | `publish/pipeline.py` — all labels now `[1/7]`–`[7/7]` |
| DC-003 | `silero_vad` missing from `_builtin_defaults()` in `registry.py` | `models/registry.py:169` — `silero_vad` `ModelEntry` added to `_builtin_defaults()` |
| P4-F | CTA retry count hardcoded to 3 (only non-configurable retry) | `config/settings.py:440` — `cta_max_retries: int = 3`; `cta/pipeline.py:45` reads it via `getattr(settings, "cta_max_retries", 3)` |

### Phase 0 Structural Extraction (2026-07-12, commits `28bdfb9`–`06c358b`)

Providers, LAMM, and generic domain models extracted to `src/video_core/`:
- `video_core/providers/{llm,search,image,tts,vision}/` — all provider ABCs + implementations
- `video_core/models/` — LAMM (`LocalAIModelManager`, registry, bundle, capabilities)
- `video_core/domain/{llm,search,image}.py` — `LLMResponse`, `SearchResult`, `ImageRequest`
- `providers/tts/pacing/` stays in `ytfactory/` (factory-specific)
- Layering rule enforced by `scripts/check_layering.py`; known open Bucket-C deps: `ytfactory.config.settings`, `ytfactory.shared.constants` (Phase 1)
- Test baseline held at **2159 passing, 0 failing** throughout every move step.

---

## Still Open

| ID | Description |
|---|---|
| MW-003 | BGM not independently controllable in incremental build — unchanged structural situation; BGM embedded in `VideoPipeline._apply_bgm()`, no named `bgm` stage in incremental engine |
| AS-001 | BGM dual-path smell — `BGMPipeline` (standalone `mix-bgm`) vs `VideoPipeline._apply_bgm()` (build path) — unchanged |
| AS-002 | `video_renderer_node` (agentic) duplicates `MotionPlanner`/`TransitionPlanner`/`EffectsPlanner` instantiation from `VideoPipeline` (sequential) — unchanged |
| CI-001 – CI-006 | Code defaults vs documented `.env` values — unchanged; running system uses `.env` overrides, but fresh installs diverge |

---

## Test Count

| | Count |
|---|---|
| Baseline (2026-07-10) | 2124 passing, 0 failing |
| At audit time (2026-07-12) | 2156 passing (+32), 3 failing |
| After regression fixes (2026-07-12) | **2159 passing** (+35), **0 failing** |
| After Phase 0 + MW-005/AS-003/DC-002 cleanup (2026-07-12) | **2161 passing** (+37), **0 failing** |

New test files accounting for the +35 (audit baseline):
`tests/test_cta_overlay_engine.py` · `tests/test_image_remediation_orchestrator.py` ·
`tests/test_model_bundle.py` · `tests/test_prompt_remediation_builder.py` ·
`tests/test_benchmark_vision_review.py` · `tests/test_video_renderer_missing_audio.py` ·
`tests/test_vision_provider.py` (expanded)

+2 new tests for MW-005 in `tests/test_incremental.py` (`TestBuildPipelineIncrementalScript`).

**3 regressions introduced by this diff — all fixed post-audit:**

| Test | Root cause | Fix |
|---|---|---|
| `test_bootstrap.py::TestBootstrapEngine::test_setup_skips_when_already_done` | `bootstrap/engine.py` Phase 0 (ML package checks) now runs unconditionally before the manifest check; test expected 1 check, got 4 | Patch `install_ml_packages → []` in that test |
| `test_image_prompt_engine.py::TestEnrichForProvider::test_does_not_double_append_reinforcement` | `_ANATOMY_REINFORCEMENT` injects "fingers" and "body" (both `_HUMAN_INDICATORS`) into the prompt; second `enrich_for_provider` call falsely enters human-quality and clothing-policy blocks that the first call correctly skipped | Compute `_already_enriched = _ANATOMY_REINFORCEMENT in prompt`; gate both blocks on `not _already_enriched`; also change `endswith` → `not in` for `_ANATOMY_REINFORCEMENT` guard |
| `test_kokoro_provider.py::TestKokoroPipelineLazyImport::test_loads_kpipeline_on_first_call` | `kokoro.py` now passes `repo_id="hexgrad/Kokoro-82M"` to `KPipeline()` to suppress a deprecation warning | Update assertion to `assert_called_once_with(lang_code="a", repo_id="hexgrad/Kokoro-82M")` |

---

## Unchanged Sections

Pipeline diagrams, component diagram, data flow diagram, provider inconsistencies (PI-001 – PI-006),
and registry inconsistencies (RI-001 – RI-004): unchanged from `ARCHITECTURE_AUDIT_2026_07_10.md` —
see that file; not reproduced here.

**Pipeline diagram delta only** (since `agents/graph.py` structurally changed — MW-001):

```
PATH A agentic — updated edge:
  video_concatenator → [NEW] cta → quality_review
  (was: video_concatenator → quality_review)
```

All other nodes and edges in the diagram are unchanged.
