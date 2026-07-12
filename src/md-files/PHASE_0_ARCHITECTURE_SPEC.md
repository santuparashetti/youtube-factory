# Video Factory Platform — Phase 0 Architecture Spec (Consolidated)

**Status:** Replaces `ARCHITECTURE_BLUEPRINT_V2`, `SDK_ARCHITECTURE_SPEC_V4`,
`IMPLEMENTATION_SPEC_V5`, `API_SDK_REFERENCE_V6`, and `PROPOSED_SPEC`.
**Scope:** ytfactory repo only. Grounded in `MASTER_CONTEXT_UPDATED.md`,
`ARCHITECTURE_AUDIT_2026_07_10.md`, and `ARCHITECTURE_AUDIT_2026_07_12.md`
(incremental). **Current baseline: 2159 tests passing, 0 failing** (was
2124 at 07-10; +35 net, 3 regressions introduced and fixed in the 07-12 diff).

---

## 0. Why this replaces five documents

V2/V4/V5/V6 describe the same three-layer model (`video_core` /
`factory_sdk` / factories) four times with different headings. None of
them reference a single real ytfactory file path. `PROPOSED_SPEC` is the
only one that correctly scopes itself to "architectural preparation only,
no behavior change" — that framing is kept; the rest is discarded.

This document is the only Phase 0 charter going forward. SDK-layer ideas
(plugin registry, lifecycle hooks, CLI bootstrap) from the old docs are
parked in **Appendix B — Deferred, Not Phase 0** and should not be built
until a second factory actually exists and needs them.

---

## 1. Purpose

Prepare the repo so a second factory *could* be added later, without:
- touching pipeline behavior
- touching CLI behavior
- touching output artifacts
- fixing unrelated bugs in the same pass

This is a structural move, not a feature change. If a diff in this phase
changes what a rendered video looks like, it's out of scope.

## 2. Non-Goals

- No stickman_factory (or any second factory) implementation
- No `factory_sdk` layer — deferred (see Appendix B)
- No fixing of audit findings (P1–P4) inside this same pass — see §3
- No Settings/config schema split — deferred (see §6)
- No workspace layout changes

---

## 3. Precondition: freeze list (updated per 2026-07-12 incremental audit)

**Update:** MW-001, MW-002, BI-001, and BI-002 — the four items that
previously gated Phase 0 — are now resolved (confirmed 07-12). The
extraction is no longer blocked. What's left:

| ID | Issue | File(s) | Status | Phase 0 conflict |
|---|---|---|---|---|
| MW-005 [NEW, MEDIUM] | `run_incremental()` skips `ScriptEnhancerPipeline` — MW-002's fix only covers the full `run()` path | `build/pipeline.py:105–200` | Open | None — `build/pipeline.py` is Bucket B, untouched by Phase 0 either way. Fix on its own schedule. |
| BI-003 / DC-002 | ElevenLabs stub unreachable (`ValueError` now raised, but `elevenlabs.py` never imported) | `providers/tts/factory.py`, `providers/tts/elevenlabs.py` | Open | **Directly in the Bucket A move path** — `providers/tts/` is being relocated in Step 4. See §5 note. |
| AS-001 | BGM dual-path (`BGMPipeline` vs `VideoPipeline._apply_bgm()`) | `bgm/`, `video/pipeline.py` | Open | None — Bucket B |
| AS-002 | Agentic/sequential renderer duplication | `agents/nodes/`, `video/pipeline.py` | Open | None — Bucket B |
| AS-003 | `GeminiScenePlanner` alias file now dead (no consumers) | `scenes/planner/gemini_planner.py` | Open, cleanup-only | None — Bucket B |
| CI-001–006 | Code defaults vs. `.env` values | various | Open | None |

**Net effect:** no precondition blocks Step 3 onward in §8 any more.
The only decision needed before Step 4 is what to do with the dead
`elevenlabs.py` stub — see §5.

---

## 4. Ground truth caveat

Everything below is built from `MASTER_CONTEXT_UPDATED.md` and the audit
— both are documentation, and the audit itself caught the docs being
stale in places (validator count 8 vs 11 vs 12 actual). **Before moving
anything, re-verify the bucket table in §5 against the live filesystem**
(the Claude Code prompt in the companion file does this as step 1).

---

## 5. Module Bucket Audit

Real paths under `src/ytfactory/`, bucketed against the test: *"would
three unrelated factories reuse this completely unchanged?"*

### Bucket A — Move to `video_core` in Phase 0 (high confidence)

These have no YouTube-specific business logic in the documented
description — they're provider abstractions and generic model lifecycle.

| Path | What it is | Notes |
|---|---|---|
| `providers/llm/base.py` + factory | LLM provider ABC + `get_llm_provider()` | Already provider-agnostic by design |
| `providers/search/base.py` + factory | Search provider ABC | Tavily-only today, interface is generic |
| `providers/image/base.py` + factory | Image provider ABC | HF/Gemini implementations, generic interface |
| `providers/tts/base.py` + factory (excl. `pacing/`) | TTS provider ABC | **Do not move `providers/tts/pacing/`**. `elevenlabs.py` stub moves along with the directory as-is — DC-002 is a dead-code cleanup decision, not a structural one; don't fold that fix into this move. |
| `providers/vision/` (base, models, mock, local, factory, **+ `llama_cpp_provider.py`, new since 07-12**) | Vision provider ABC + LAMM-backed local impl | Already documented as "completely model-agnostic"; new provider file follows the same pattern, include it in the move |
| `models/` (LAMM: `manager.py`, `registry.py`, `backend.py`, `manifest.py`, `capabilities.py`, `bundle.py`) | Local AI Model Manager — single authority for model lifecycle | Explicitly designed as infra ("no feature pipeline may download models directly") — best Phase 0 candidate after providers |
| `domain/` models: `LLMResponse`, `SearchResult`, `ImageRequest` | Generic provider I/O shapes | Leave `Project` (YT-specific stage dict) in the factory — see Bucket B |

**Do first, in this order:** `providers/*` (smallest blast radius, most
obviously generic) → `models/` (LAMM, larger but self-contained) →
generic `domain/` response models.

### Bucket B — Stays in factory (confirmed factory-specific)

| Path | Why it stays |
|---|---|
| `review/` (all 7 layers: stages, validation, rca, scoring, efl, debug, remediation) | Validators check YouTube content policy (human detection, clothing policy, BGM ducking, CTA) — not generic |
| `images/human_detector.py`, `images/clothing_policy.py` | Product/brand policy, encodes specific cultural-authenticity rules |
| `providers/tts/pacing/` (Contemplative Pacing Engine) | Tuned specifically for spiritual-content narration rhythm |
| `bgm/` (mixer, vad, debug, pipeline) | Ducking curves and pause classification tuned to this content type; a podcast_factory would likely need different defaults, not this exact code |
| `branding/` (brand_config, validator) | Atma Theory-specific script structure enforcement |
| `publish/` (all generators) | YouTube-specific metadata/thumbnail/upload package |
| `scene/` (scene state machine) | YouTube-specific scene review workflow |
| `subtitles/editor/` (Subtitle Intelligence Engine) | LLM editorial pass tuned to this brand's style, not proven generic yet |
| `domain.Project` | Stage-status dict is YT pipeline-specific |
| `agents/` (LangGraph graph + nodes, **incl. new `agents/nodes/cta.py`**), `build/pipeline.py` | Orchestration IS the product workflow, per architectural principle in all five source docs |
| `script_enhancer/pipeline.py` (new since 07-12) | Brand structure enforcement — product-specific, same category as `branding/` |
| `workflow/image_remediation_orchestrator.py` (new since 07-12) | Orchestrates image review/remediation loop — same category as existing `images/` policy modules |
| `prompts/prompt_remediation_builder.py` (new since 07-12) | Builds corrective prompt text from vision review failures — content-specific, same category as `images/human_detector.py` |
| `review/validation/rules/cta.py` (new since 07-12) | New validator rule — part of the existing `review/` quality gate, same bucket as the rest of `review/` |
| `benchmark/` (confirmed 2026-07-12, resolved from prior "ambiguous" status) | `BenchmarkEngine` directly imports `ImageReviewEngine`/`ImageReviewConfig` from `ytfactory.images.*` and builds a `_NullImageProvider` solely to satisfy that engine's constructor. `BenchmarkScene` bakes in the YT scene schema (`visual_prompt`, `scene_type: "generated_image"`, YT pixel dimensions) and `hard_fails.py`'s `RULE_MATCHERS` encode YT-specific policy (clothing violation, anatomy rules). No `BenchmarkTarget` ABC exists — there's no plug point for a TTS/LLM/subtitle benchmark. Reusing this by a second factory would require a full rewrite of `engine.py`, not a relocation. |

### Bucket C — Ambiguous / defer to Phase 1 (needs a second factory to prove it)

| Path | Why deferred |
|---|---|
| `config/settings.py` | One monolithic `Settings` object mixes shared (API keys, logging) and factory-specific (BGM, CTA, image review) fields. Splitting this is itself a non-trivial refactor with real regression risk — don't fold it into Phase 0. |
| `bootstrap/` (doctor, healer, env_checker, model_bootstrap) | Generic shape (env checks, self-healing) but current checks are hardcoded to WhisperX/Kokoro/vision model names — would need parameterization before reuse |
| `incremental/` (checksum manifest, dirty-stage detection) | Generic *concept* (skip clean stages) but `deps.py` stage graph (`"bgm": "video"` etc.) is YT-pipeline-specific |
| `subtitles/segmenter.py`, `subtitles/` core engine (excl. `editor/`) | Plausibly generic (any video factory needs subtitle timing) but unproven — only one consumer exists today |
| `video/ffmpeg.py` | Needs a closer look: if it's a thin FFmpeg subprocess wrapper, Bucket A; if `render_continuous()` embeds cinematic decisions (MotionPlanner/TransitionPlanner/EffectsPlanner per AS-002), Bucket B. Audit before moving. |
| `storage/project_repository.py`, `shared/constants.py` | `WORKSPACE_DIR`/`PROJECT_FILE` naming assumes YT's `workspace/jobs/<id>/` layout — low value to move until a second factory needs a different layout |

---

## 6. Target Layout (Phase 0 only — no `factory_sdk`)

```
src/
├── video_core/
│   ├── providers/          # llm, search, image, tts (base+factory only), vision
│   ├── models/              # LAMM, unchanged internals
│   └── domain/              # LLMResponse, SearchResult, ImageRequest
│
└── ytfactory/                # unchanged — everything else stays here
    ├── review/
    ├── bgm/
    ├── publish/
    ├── branding/
    ├── scene/
    ├── build/
    ├── agents/
    ├── config/
    └── ... (rest unchanged)
```

No `factory_sdk` package, no `stickman_factory` scaffold yet. Both are
Appendix B items — build them when there's a second real consumer.

---

## 7. Dependency rule (unchanged from prior drafts, this part was right)

```
Allowed:    ytfactory  →  video_core
Forbidden:  video_core →  ytfactory
```

Enforce with a lint rule or CI import-check once the move is done — not
before, since there's nothing to enforce yet in a single-package repo.

---

## 8. Migration sequence

1. Snapshot: `uv run pytest tests/` — record pass count as baseline (**2159 passing, 0 failing as of 07-12** — re-confirm before starting, since more time will have passed).
2. ~~Fix audit P1 items~~ — done as of 07-12 (MW-001, MW-002, BI-001, BI-002 resolved). Confirm MW-005 (incremental path skips script enhancer) doesn't need fixing first — it doesn't block Phase 0 since `build/pipeline.py` isn't touched, but note it as a known open item so it isn't mistaken for a Phase 0 regression later.
3. Create `src/video_core/` package skeleton (empty `__init__.py` files only).
4. Move `providers/llm/` → `video_core/providers/llm/`. Update imports repo-wide. Run tests. Commit.
5. Repeat step 4 one provider type at a time: `search`, `image`, `tts` (base+factory, not `pacing/`), `vision`. One module = one commit = one test run.
6. Move `models/` (LAMM) → `video_core/models/`. Update imports. Run tests. Commit.
7. Move generic `domain/` response models → `video_core/domain/`. Leave `Project` in place. Run tests. Commit.
8. Add the CI/lint import-direction check from §7.
9. Update `CLAUDE.md` and `MASTER_CONTEXT_UPDATED.md` to reflect new import paths.

No parallelism across steps 4–7 — sequential, one module per commit, so
a regression maps to exactly one change.

---

## 9. Success Criteria

- `uv run pytest tests/` passes at the same count as the pre-migration baseline
- CLI behavior identical — every command in CLAUDE.md's workflow list still works unchanged
- No file in Bucket B or Bucket C was touched
- `video_core` has zero imports from `ytfactory`
- Total diff is import-path and file-location changes only — no logic changes

---

## Appendix A — Explicitly out of scope, revisit only after a 2nd factory exists

- `factory_sdk` (lifecycle manager, plugin registry, CLI bootstrap, templates)
- `stickman_factory` (or any) scaffold
- Settings schema split (shared vs. factory config)
- Standardized workspace manifest format
- Standardized artifact metadata schema (checksum/id/producer on every artifact)
- Any of Bucket C, until proven by a second consumer

## Appendix B — Original SDK/API ideas, preserved for later reference

The four superseded docs (V2/V4/V5/V6) contained reasonable *long-term*
ideas — `Factory`/`Renderer`/`Workflow` interface contracts, structured
lifecycle events (`factory.started`, `stage.completed`, etc.), a plugin
registry for providers/renderers/publishers. None of this is discarded,
it's just sequenced correctly: design these against two real factories'
actual needs, not zero.
