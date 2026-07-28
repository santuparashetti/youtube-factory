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
**Test count:** 3088 passing, 1 skipped, 6 pre-existing unrelated failures (subtitle-burn/CLI, predate this work; as of 2026-07-28)

## 2026-07-28 — Composer replaces enhancer + Structural Retention Pass (whole-cloth rearchitecture)
**Why:** Individual structural moves (open loop, parallel-example cut, shadow beat, climax breath)
could all fire correctly and Editorial QA could pass clean, yet the composed script read worse —
reordering already-finished prose fragmented coherence and lost the piece's soul. No stage held the
whole script as one coherent thing while writing it; the transform model (edit → restructure →
check) is architecturally incapable of that. Fix: compose at the source in one continuous act, not
operate on prose after the fact.

**Architecture:** Script generation moved from `DocumentaryScriptEnhancerPipeline` (Pass 1/2/3,
mode-selection shorten/polish/expand, 80% coverage floor, no-reorder ban) + Structural Retention
Pass (5 post-hoc moves) → single whole-cloth `ComposerPipeline`. New flow: base script → `composer`
→ `editorial_qa` → `human_review_final_script` → `scene_planner`. Old enhancer
(`script_enhancer/pipeline.py`) and Structural Retention Pass (`structural_retention/`) **archived,
not deleted** — importable, CLI commands and full test suites retained, but unwired from
`agents/graph.py`, `build/pipeline.py`, `two_phase/pipeline.py`.

**Composer** (`composer/pipeline.py::ComposerPipeline`): one LLM call, temp 0.6. System prompt = full
`ATMA_THEORY_COMPOSER.md` (`agents/prompts/composer.py::build_composer_system_prompt`, `lru_cache`);
user content = base script. Structural principles are now composition directives inside the
framework text, not post-hoc moves on finished prose. No mode selection, no coverage floor, no
reorder ban — removed, they belong to the retired transform model. Length targets 7-9 min via the
framework's LENGTH section (understanding, not a word-count gate) — `TARGET_MIN_MINUTES=7` /
`TARGET_MAX_MINUTES=9`. `build_recompose_directive()` written but dormant/unwired — whole-piece
recompose fallback for out-of-range output, to be wired only if real usage proves it's needed
(single-call eagle output has landed in-range on every real run so far). Scripture protection
carried over unchanged from the retired pipeline.

**Editorial QA** (`editorial_qa/`) kept, mechanism unchanged, now positioned as final reader directly
after `composer` (was after Structural Retention Pass). 6 evidence-bearing checks
(`pipeline.py::CHECK_NAMES`); a verdict with no cited evidence is `invalid`, never counted as a flag
(`_validate_evidence`) — same naming-requirement lesson as the Structural Retention Pass's
rationalization-bug fix. Flags only — never gates/blocks/rewrites (`EDITORIAL_QA_STAGE_SPEC.md`).
Ledger (`ledger.py::QALedger`, append-only JSONL at `workspace/editorial_qa/ledger.jsonl`,
cross-project) + pattern promoter (`promoter.py::PatternPromoter`, proposes a generation-prompt
change only at ≥N-of-M flag rate, human approve/dismiss via `ytfactory qa-promotions`, never
auto-applies). Phase 2 scoped auto-fixer documented in spec but NOT built — gated on ~15-20 real
scripts of ledger data.

**Review checkpoint:** `human_review_final_script_node` (`agents/nodes/human_review.py`) +
`FinalScriptReviewGate`/`checkpoint.py` (`editorial_qa/`) — SHA-256 hash-guard on `script.md`.
Unchanged since last review → skip straight through; hand-edited during the pause → re-runs
Editorial QA on the edit before continuing (report-only). Wired into the LangGraph path and
`TwoPhasePipeline.run_prep_only()` (Phase 1 resume-skip: existing finalized `script.md` skips
composer+QA regeneration entirely).

**QA score fix:** the reviewer LLM (deepseek-v3.2) reliably inverted the sign on `editorial_score`
(real production bug: `-9.2`; reproduced `-1.0`/`-9.5` even after prompt strengthening). Replaced
with `pipeline.py::_derive_editorial_score` — deterministic, code-only: start at 10.0,
`-FLAGGED_PENALTY` (1.5) per flagged check, `-INVALID_PENALTY` (2.0) per invalid check, clamp to
`[0, 10]`. Model no longer asked for this field at all (removed from `agents/prompts/editorial_qa.py`
schema). Range assertion kept in `pipeline.py` and `ledger.py::QALedger.append()` as free insurance
— should never fire now that the value is our own arithmetic. Backfilled the 2 real ledger entries +
their `qa/editorial-qa-report.json` files to the new formula.

**Brand signature:** closing line changed to `"This is the Atma Theory."` (was `"This is Atma
Theory."`). Source of truth is `config/brand_config.yaml`'s `closing.template` +
`branding/config.py::_DEFAULT_CLOSING` fallback — matched via
`agents/prompts/branding.py::CLOSING_VARIATIONS` inside
`scene_planner.py::_mark_asset_scenes()`/`_is_closing_scene()`, **not** a hardcoded string in
scene_planner itself. Matching verified working end-to-end with a temporarily-enabled test config.
Note: `closing`/`cta`/`signature` are currently `enabled: false` in committed `brand_config.yaml`,
so brand-card placement is presently inactive regardless — unrelated pre-existing state, not touched.

**Validated (eagle script, real LLM runs, not fixtures):** composer output is tighter (958-1089
words vs. 1325 for the surgical enhancer+structural-pass version) and more coherent — one continuous
voice, no assembled seams. Editorial judgment improved on at least one real case: composer kept a
story (Vinoba Bhave's chapati parable) the surgical structural pass had cut, correctly judging it a
different narrative shape (mastery-of-small-things vs. impossible-and-prevailed) rather than a 3rd
redundant instance. Re-composition produces a materially different draft each run (non-memorized)
and Editorial QA flags differ run-to-run — genuine re-evaluation, not a cached template.

**Superseded:** `## 2026-07-17 — ADR-0011 Two-Pass Cinematic Script Enhancer` (below) and the
`script_enhancer` node in `## Two Execution Paths`'s graph description no longer describe the active
script-generation path — see this entry. Left in place for history;
`DocumentaryScriptEnhancerPipeline` itself is archived, not deleted.

+~120 tests (`test_composer.py`, `test_editorial_qa.py`, `test_final_script_review_gate.py`, plus
wiring updates to `test_two_phase_pipeline.py`, `test_incremental.py`, `test_light_normalization.py`,
`test_youtube_ingest.py`). Test count → 3088 passing, 1 skipped, 6 pre-existing unrelated failures.

## 2026-07-26 — Brand card: forced static motion + no subtitle burn-in
Two related brand-card-only fixes, requested and verified separately.
**Motion** (`video_core/cinematic/motion.py`, `rebalancer.py`): brand_card
scenes were inheriting the generic asset-scene `_asset_motion()` default
(`push_in`/slow_zoom) — grouped with plain `"asset"` scenes in
`MotionPlanner.plan()`'s dispatch, so a brand card always got a Ken Burns
zoom. Fixed by short-circuiting `_asset_motion()` to a forced
`motion_type="static"` `MotionSpec` (start_scale=end_scale=1.0) whenever
`scene_type == "brand_card"`, before the `animation` string is even read;
plain `"asset"` scenes are untouched. Also had to guard two places that
could silently override it back to motion: `MotionPlanner.plan()`'s 3+
repeat-run variety override, and `MotionRebalancer.rebalance()`'s long-run
substitution (`get_acceptable_motions("asset")` defaults to `["drift"]`,
not empty, so a static brand_card caught in a same-motion run would
otherwise get swapped). No renderer change needed —
`build_zoompan_filter()` already had a first-class static→scale/crop
no-op path.
**Subtitles** (`video/ffmpeg.py`, `video/pipeline.py`,
`agents/nodes/video_renderer.py`): brand card's `.ass` file (Phase 1 still
generates it, unchanged) was being burned into the final frame by both
render paths. `FFmpegRenderer.render()` gained a `scene_type` param that
skips the `subtitles=` filter when `"brand_card"`; `render_continuous()`
checks `scene.get("scene_type")` inline before resolving which subtitle
file to feed the filter chain. Narration audio is unaffected in both
cases — only the caption filter is skipped.
**Also:** fixed a flaky test from the prior brand-card-cache-fix commit
that asserted against the live `config/brand_config.yaml` — its
closing/cta/signature `enabled` flags are toggled operationally outside
git, so the test now uses an isolated fixture config instead.
+12 tests (`test_video_validation_rules.py::TestBrandCardStaticMotion`,
`test_brand_card_no_subtitle_burn.py`). Test count → 2923.

## 2026-07-26 — Brand card asset cache investigation (no code change needed)
Investigated a suspected bug: brand card PNG getting cached into
`workspace/jobs/<id>/images/` and reused stale. Traced every brand_card
touch point (`agents/nodes/scene_assets.py`, `video/pipeline.py`,
`images/verify.py`, all 12 review validators) — **the caching bug did not
exist in current code**; it was already fixed by earlier commits
(`f5845d2`, `cb74cc4`, `66d2ae7`). `scene_assets.py` *reassigns*
`image_path = asset_path` for `scene_type in ("asset", "brand_card")`, it
never copies bytes; `scene-plan.json`'s `asset_path` is always
`assets/branding/...`, never job-local; vision QA, remediation
auto-regeneration, and image-integrity validation all explicitly skip
asset/brand_card scenes. Added two regression-guard tests
(`test_brand_card_cache_fix.py`) instead of speculative code changes, so a
future refactor can't silently reintroduce the bug. Stale
`workspace/jobs/*/images/scene-0NN.png` files found in one older completed
job don't even hash-match the brand PNG — they're orphaned AI-generated
images from before that scene index was reassigned to `brand_card` on a
re-plan, unrelated to the suspected caching path. +2 tests. Test count → 2911.

## 2026-07-26 — Task 2.11: Overlay Fixes (visual keyword trigger, brightness, grain threshold)
**Spec:** `docs/image-prompt/tasks/task-2.11-overlay-fixes.md`. Three fixes
to `video/overlay.py` + `video/pipeline.py`:
1. **Visual keyword trigger** — rain/particles/smoke/fog overlays now also
   fire on a `visual_prompt` keyword match (e.g. "downpour") when
   motion_type/mood didn't already select a category, via new
   `_category_from_visual_prompt()`; god_rays and everything else stay
   motion_type/mood-only. `fog` keyword matches route through the existing
   `_MOTION_ALIASES` to the `smoke` manifest category (there's no `fog` key
   in the manifest), same as `motion_type="fog"` already does.
2. **No darkening** — new `OVERLAY_MAX_OPACITIES` (grain 0.03,
   rain/god_rays 0.12, particles/smoke 0.10). Mood-overlay blend is now
   hard-forced to `screen` and grain to `overlay` (not read from the
   manifest, so a future manifest edit can't reintroduce darkening);
   opacity is always clamped to the category max. `assets/overlays/overlay_manifest.json`
   values brought down to match.
3. **Grain threshold** — `_should_apply_grain()` now requires ≥40% of
   non-brand-card scenes to match era/mood/style (was: any single scene),
   replacing a rule that fired on nearly every video since one historical
   scene sufficed.
+14 tests (`test_overlay_compositing.py`). Test count → 2909.

## 2026-07-26 — docs/ reorganized (move-only, no content changes)
Structure: `adr/`, `architecture/` (new), `branding/`, `image-prompt/` (renamed
from `image-prompt-generation/`, gained `tasks/` subfolder for all
task-2.2–2.10 + Task_0/1/2_1 specs, moved from `script/`), `video/`,
`tts/`, `review/` (renamed from `video-quality-review/`), `pipeline/` (new),
`plug-and-play-setup/` (untouched), `publishing/`, `roadmap/`, `fix-prompts/`
(new, historical kilo-code fix prompts), `reference/` (new, CLI_REFERENCE.md).
`docs/context/MASTER_CONTEXT.md` and `docs/script/` (remaining ADR-0010/11/12
+ script-enhancer specs) untouched. All `docs/script/task-2.X...` and
`docs/image-prompt-generation/...` refs in this file updated to their new
paths accordingly — if you have an older cached path for any spec doc below,
it moved to `image-prompt/tasks/` or `image-prompt/`.

## 2026-07-26 — Task 2.10: Phase 1.5 Image QA Gate
**Spec:** `docs/image-prompt/tasks/task-2.10-phase1.5-image-qa.md`. New CLI:
`ytfactory verify-images --project <id> [--scenes 1,5,12] [--auto]`.
New `src/ytfactory/images/verify.py`: `verify_scene()`/`verify_all_scenes()`
call the REAL `VisionProvider.review(image_path, visual_prompt, scene_context)`
→ `VisionReviewResult` (status/recommend_regeneration/issues) — the doc
assumed a fictional `vision_client.verify(image_b64=...)` text API that
doesn't exist in this codebase; mapped `recommend_regeneration`→REGENERATE,
`issues[].description`→reasons instead. `_parse_qa_response()` kept as a
tested standalone text-parser per the doc's spec (not used by the real
vision path, which returns structured results already). Writes
`images/image_qa_report.json`; exit code 1 if any REGENERATE/MISSING.
Also replaced `image_generation_rules.md`'s content with v2 (Storyboard
Mode) — written by `two_phase/pipeline.py::_write_image_prompts_manifest()`
via new `IMAGE_GENERATION_RULES_V2` constant. New settings
`image_qa_enabled`/`image_qa_max_tokens` (max_tokens reserved, not wired —
no such param on `VisionProvider.review()`). +14 tests. Test count → 2895.

## 2026-07-26 — Task 2.9: Grain Overlay — Conditional, Not Mandatory
**Spec:** `docs/image-prompt/tasks/task-2.9-grain-conditional.md`. Grain no
longer applies unconditionally to every video. New
`OverlayCompositor._should_apply_grain(scenes)` (`video/overlay.py`) fires
only when any non-brand-card scene's `visual_metadata` has era∈{HISTORICAL,
ANCIENT, SYMBOLIC, TRANSITIONAL}, mood∈{reverent,mysterious,reflective,
fearful,lonely}, or visual_style∈{CINEMATIC,DOCUMENTARY}. **Deviation:** the
doc's pseudocode read flat `scene.get("era")` — real schema nests these
under `scene["visual_metadata"]` (dict or `VisualMetadata` object) as
`era`/`mood`/`visual_style` (not `style`). New setting
`overlay_grain_enabled` (default True, hard override independent of the
composition check) in `ytfactory/config/settings.py` (not `SharedSettings` —
same layering-rule reasoning as prior overlay/TTS settings). `_apply_overlays()`
now logs exactly why grain fired or was skipped. +12 tests. Test count → 2870.

## 2026-07-26 — Task 2.8: Storyboard Mode + Strict Scene Fidelity
**Spec:** `docs/image-prompt/tasks/task-2.8-storyboard-mode.md`. Two new
blocks (`STORYBOARD_MODE_BLOCK`, `STRICT_SCENE_FIDELITY_BLOCK`) prepended at
position 0 of `_VISUAL_PROMPTS_TEMPLATE` — instructs the generation model
that `visual_prompt` is authoritative, narration is mood-only context, no
inventing subjects, treat every scene as an independent storyboard frame.
New `prepend_storyboard_header()` (idempotent) applied to every non-
brand-card `visual_prompt` written to `image_prompts_manifest.json`
(`two_phase/pipeline.py`) and `IMAGE_PROMPTS.md` (`scene_planner.py`'s
`_write_prompts_file`) — the manual-image-gen workflow never sees the
generation template, so the instruction has to travel with the prompt text
itself. **Deviation:** doc's tests assumed a static `VISUAL_PROMPT_TEMPLATE`
containing the anchor/narration text; actual constant is
`_VISUAL_PROMPTS_TEMPLATE` and anchor/narration are injected per-scene
dynamically — wrote tests against the real structure. Also fixed 2 Task 2.5
tests that asserted the *old* position-0 block (forbidden words). +11 tests.
Test count → 2881.

## 2026-07-26 — Overlay Compositing: Audit + Fix (untracked feature, never wired)
Audit found `OverlayCompositor` (`video/overlay.py`) was never called from
anywhere in the pipeline — and even if wired onto per-scene `video/scene-NNN.mp4`
clips (what its API was shaped for), it would have had zero effect on the
shipped video: `render_continuous()` builds `final.mp4` directly from raw
assets in one continuous stream, never reading those per-scene clips (they
exist only for the review/remediation system). Fixed: new `_apply_overlays()`
in `video/pipeline.py`, inserted between `render_continuous()` and
`_apply_bgm()` (all call sites, incl. resume-guard). Composites via
time-gated blend stages (`enable='between(t,start,end)'` from cumulative
scene durations) directly on the continuous stream — no slicing/re-concat,
preserving the no-GOP-boundary property. Grain always last, whole-video, no
time gate. Deleted a second, broken, unused `apply_overlays()` method
(passed `{}` instead of the scene). New `overlay_assets_dir` setting
(previously hardcoded `assets/overlays`). +15 tests
(`tests/test_overlay_compositing.py`); fixed 3 pre-existing tests that fully
mocked `_apply_bgm` without knowing about the new intermediate call. Test
count → 2858 (baseline going in: 2843).

## 2026-07-26 — Task 2.7: Narrative-Visual Bridge
**Spec:** `docs/image-prompt/tasks/task-2.7-narrative-visual-bridge.md`.
Scope: `agents/nodes/scene_planner.py` + `agents/prompts/scene_planner.py`.

Root cause: the visual-prompt generation template received style/entity/camera
metadata but never an explicit answer to "what does this narration show?" —
`abstract` scenes with empty extracted characters had zero narrative direction
and drifted to generic "spiritual documentary aesthetic object" imagery
(journal, candle, sandal).

- **`_build_visual_anchors()` / `_build_anchor_batch_prompt()`**
  (`agents/nodes/scene_planner.py`): one batch LLM call (reuses the Task 2.6
  `_get_cheap_llm(settings, "llm_validation")` client — its instantiation
  moved earlier so both this pass and the later LLM validation step share one
  client) that reads every scene's narration and returns a one-sentence
  `visual_anchor` per scene — literal, specific, named subjects only.
  Brand-card scenes excluded (fixed asset, not generated). Non-blocking: any
  parse failure/exception → empty dict, scenes generate exactly as before.
  Few-shot examples included in the prompt.
- **`_build_anchor_block()` / `_build_narration_context_block()`**
  (`agents/prompts/scene_planner.py`): injected per-scene inside
  `build_visual_prompts_prompt()`'s scene-list loop (same integration point as
  Task 2.5's environment block — this codebase batches scenes per generation
  call, so there's no separate per-scene prompt formatter to hook). The anchor
  block ("REQUIRED VISUAL: ...") only appears when an anchor exists; the
  narration block ("NARRATION FOR THIS SCENE: ...") is unconditional per the
  spec.
- `scene["visual_anchor"]` is set directly on the same dict objects
  serialized into `scene-plan.json` — persisted with zero extra code.
- New setting `visual_anchor_enabled` (default True) — added to
  `ytfactory/config/settings.py`, not `SharedSettings`, same layering-rule
  reasoning as Task 2.6. `VISUAL_ANCHOR_ENABLED` added to `.env.example`.
- +13 tests in `tests/test_task_2_7_narrative_visual_bridge.py`. Full suite:
  2833 passing (was 2820), same 1 pre-existing unrelated failure, no regressions.

## 2026-07-26 — Task 2.6: Deterministic Fixes + LLM Validation Layer
**Spec:** `docs/image-prompt/tasks/task-2.6-deterministic-plus-llm.md`. Baseline: 13/28 PASS after Task 2.5.
Scope: `validators.py` + `agents/nodes/scene_planner.py` + `agents/prompts/scene_planner.py`.

**Part 1 — two deterministic fixes:**
- Fix 1A: `should_skip_environment_check()` gained 3 catch-all rules on top of
  the expanded `ABSTRACT_ENVIRONMENTS` set — `env.startswith("implied")`,
  `"no specific" in env`, and `"realm" in env` when the phrase is ≤5 words
  (avoids over-matching a long concrete description that happens to say "realm").
- Fix 1B: removed the story-time check entirely (was never part of any spec —
  a semantic rule keyword matching can't satisfy, e.g. "day of celebration").

**Part 2 — new LLM validation layer** for `ENVIRONMENT_MISMATCH` /
`HUMAN_CLASSIFICATION_VIOLATED` (the two checks needing semantic understanding):
called ONLY when these are the sole remaining critical errors for a scene
(never on scenes that already pass, never mixed with structural failures like
`FORBIDDEN_CHARACTER`). `LLM_VALIDATABLE_CHECKS`, `_should_use_llm_validation()`,
`_run_llm_validation()` in `scene_planner.py`; `LLM_VALIDATION_PROMPT` +
`build_llm_validation_prompt()` in `agents/prompts/scene_planner.py`. Parse
failure or any exception → treated as PASS (never blocks). New
`faithfulness_qa.llm_validated`/`llm_reason` fields. New settings:
`faithfulness_llm_validation_enabled` (default True),
`faithfulness_validator_model` (default `google/gemini-2.5-flash-lite`),
`faithfulness_validator_max_tokens` (default 150, **not actually wired** — see
deviation below). Separate cheap LLM client via the existing
`_get_cheap_llm(settings, "llm_validation")` pattern — no new client
instantiation mechanism needed.

**Part 3:** `FORBIDDEN_CHARACTER` now checks `is_equivalent_character()`
against `allowed_characters` before firing — fixes the case where entity
extraction put the same term in both `allowed_characters` and
`forbidden_characters` (e.g. allowed=["boy","mother"], forbidden
accidentally includes "boy").

**Found and fixed while here:** `scene_planner_max_retries`,
`scene_planner_json_mode`, `scene_planner_strict_schema`,
`faithfulness_gate_fail_pipeline` were genuinely duplicated between
`video_core/config/shared_settings.py` and `ytfactory/config/settings.py`
(an artifact of Task 2.2's concurrent-tool episode). Removed the duplicates
from `shared_settings.py` — scene-planner concepts are ytfactory-only per the
layering rule, so `ytfactory/config/settings.py` is their correct home. Also
added all 7 scene-planner env vars to `.env.example` for the first time (Task
2.2–2.6 vars were never there before).

**Deviations (both explicitly out of scope per the doc's own "Do NOT touch"
list, same pattern as Task 2.4):** `openai_provider.py`/`get_llm_provider()`
signatures untouched — `max_tokens` per call and the doc's
`get_llm_provider(provider=, model=, base_url=, api_key=)` pseudocode aren't
implemented; reused the existing `_get_cheap_llm` model-override pattern instead.

+25 tests in `tests/test_task_2_6_deterministic_plus_llm.py`. Full suite: 2820
passing (was 2795), same 1 pre-existing unrelated failure, no regressions.

## 2026-07-26 — Task 2.5: Three Targeted Fixes (follow-up to 2.4)
**Spec:** `docs/image-prompt/tasks/task-2.5-three-fixes.md`. Baseline: 15/30 PASS after Task 2.4.
Scope: `agents/prompts/scene_planner.py` + `agents/nodes/scene_planner.py` only.

- **Fix A:** forbidden-words block moved from mid-prompt to the literal start
  of `_VISUAL_PROMPTS_TEMPLATE` (before "You are a documentary film
  director...") — an expanded "⚠ ABSOLUTE CONSTRAINTS" block with per-word
  camera-angle alternatives and an explicit `ANIMAL_ONLY SCENES` rule.
- **Fix B:** new `_build_environment_block()` injects a per-scene
  `REQUIRED SETTING: {environment}` hard constraint read from
  `scene["scene_analysis"]["environment"]`, inline in the batch scene list
  inside `build_visual_prompts_prompt()` — covers both batch generation and
  `validators.py`'s single-scene retry prompt (same function). Skipped for
  unspecified/abstract/empty environment values.
- **Fix C — the real remaining bug:** `deterministic_result.passed` requires
  zero errors of *any* severity (critical AND minor — e.g.
  `STORY_TIME_MISSING`, `CAMERA_MISSING`), but retry feedback
  (`compose_feedback`) only ever acts on `critical_errors`. A minor-only issue
  therefore blocked PASS with empty feedback (generic "Prompt failed
  validation" message) — the same "FAIL | 0 errors" symptom as Task 2.4 Fix 1,
  but through a different mechanism (no legacy-check disagreement involved).
  Task 2.4 had already unified the retry loop to one evaluation point; this
  task tightened that point's condition from `deterministic_result.passed` to
  `not deterministic_result.critical_errors`.
- +11 tests in `tests/test_task_2_5_three_fixes.py`; one Task 2.4 source-scan
  test updated to match the tightened condition. Full suite: 2795 passing (was
  2784), same 1 pre-existing unrelated failure, no regressions.

## 2026-07-26 — Task 2.4: Validator & Generation Fix (7 targeted fixes)
**Spec:** `docs/image-prompt/tasks/task-2.4-seven-fixes.md`. Baseline going in: 6/26 PASS after Task 2.3.
Scope: `validators.py` + `agents/nodes/scene_planner.py` (+ `agents/prompts/scene_planner.py`
for Fix 5's generation-prompt wording).

1. **Zero-errors-is-pass bug:** `scene_planner.py`'s retry loop had
   `if deterministic_result.passed and legacy_passed:` — a scene with zero
   deterministic errors could still be marked FAILED if the separate LLM-based
   legacy faithfulness check (added in Task 2.2, not mentioned in this doc)
   disagreed. That's the exact "FAIL | 0 errors" log symptom. Fixed: deterministic
   pass is now unconditional; legacy disagreement is logged as a warning only.
2. **Article stripping:** `_normalize_char()` strips leading "a "/"an "/"the "
   before every character comparison in `is_equivalent_character()` — allowed
   `["a man"]` now matches detected `"man"`.
3. **Equivalence wiring:** confirmed `is_equivalent_character()` fires before
   `UNSUPPORTED_CHARACTER` is raised (it already was; the visible symptom was
   actually Fix 2's article bug). Added a DEBUG log line when a character is
   exempted via equivalence.
4. **`UNAMBIGUOUS_HUMAN_WORDS` expanded:** face/faces, shoulder/shoulders,
   torso, arm/arms, leg/legs, chest, forehead, chin, cheek, hand/hands,
   finger/fingers, eye/eyes. New `_is_animal_possessive_context()` helper: for
   `eye`/`eyes`/`hand`/`hands` **only** (per the doc's own scoping), skip the
   violation in `animal_only` scenes when the word is within 3 tokens after an
   animal name from `scene_analysis["characters"]` (e.g. "the eagle's eye").
   All other newly-added body-part words are flagged unconditionally in
   `animal_only` scenes — they were genuine misses, not false positives.
5. **Forbidden generation words:** `agents/prompts/scene_planner.py`'s
   `_VISUAL_PROMPTS_TEMPLATE` gained an explicit "FORBIDDEN WORDS" block
   (silhouette, ethereal glow, text, watermark) — these were already banned in
   the validator but nothing in the *generation* prompt told the model not to
   write them, so it kept regenerating them across retries.
6. **`ABSTRACT_ENVIRONMENTS` expanded** (~20 new entries: "inside his/her/their
   head", "the mind", "imagination", "memory", "vision", "dream", etc.) —
   substring/fuzzy matching was already in place from Task 2.3.
7. **Symbolic figures in `abstract` + no-characters-extracted scenes** ("sage",
   "elder", etc.) are now a logged WARNING, not a hard violation, when
   `scene_category == "abstract"` and `scene_analysis["characters"]` is empty —
   applied to both the `FORBIDDEN_CHARACTER` and `UNSUPPORTED_CHARACTER` code
   paths.
8. **Token efficiency (partial):** `ValidationError.to_feedback_block()` /
   `ValidationResult.feedback_text` compacted to one line per error — dropped
   the restated "VALIDATION FAILED — ..." preamble/trailer since
   `build_retry_prompt()` already supplies its own framing (saves the ~60-80
   tokens/retry the doc called out). Per-call `max_tokens` tuning and prompt
   caching were **not** implemented — both require changing
   `LLMProvider.generate()`'s signature in `openai_provider.py`, explicitly out
   of scope for this task.
- +17 tests in `tests/test_task_2_4_seven_fixes.py`. Full suite: 2784 passing
  (was 2767), same 1 pre-existing unrelated failure, no regressions.

## 2026-07-26 — Task 2.3: Story Fidelity Validator Fix
**Spec:** `docs/image-prompt/tasks/task-2.3-validator-fix.md`. Scope: `ytfactory/images/validators.py` only
(plus one call-site update in `scene_planner.py` to thread `scene_category` through).

Root cause: the validator's "semantic" checks were lexical/pattern matchers
trying to judge whether cinematic imagery *embodies* a concept — a well-written
prompt expresses "reverence" or "perseverance" through imagery, never as a
literal substring, so these checks had a 0/29 pass rate.

- Removed 6 lexical semantic checks: `NARRATION_NOT_REPRESENTED`,
  `STORY_GOAL_MISSING`, `EMOTIONAL_BEAT_MISSING`, `VISUAL_FOCUS_MISSING`,
  `PRIMARY_SUBJECT_MISSING`, `PRIMARY_ACTION_MISSING`. Kept the structural
  checks (`FORBIDDEN_CHARACTER`, `UNSUPPORTED_CHARACTER`,
  `HUMAN_CLASSIFICATION_VIOLATED`, `CAMERA_MISSING`, `SYMBOLIC_REPLACEMENT`,
  `FORBIDDEN_OBJECT`).
- `UNAMBIGUOUS_HUMAN_WORDS` set replaces the old inline 7-word human-indicator
  list for the `NO_HUMAN_ALLOWED` check. `ANIMAL_SAFE_WORDS` (pronouns/relational
  words — "her", "its", "mother") is defined but **deliberately not swept**
  even in `animal_only` scenes — adding it to the active detection set (even
  gated by `scene_category`) broke real passing scenes that never declare
  `animal_only` explicitly (e.g. "tests its wings" flagged on "its"). Kept as
  a documented safety net only.
- `CHARACTER_EQUIVALENTS` map + `is_equivalent_character()` — "woman"~"she",
  "boy"~"child", etc. — fixes `UNSUPPORTED_CHARACTER` false positives where a
  detected word and an allowed character refer to the same person differently.
- `SYMBOLIC_HUMAN_FIGURES` set — "elder", "sage", "ascetic", etc. always
  exempt from `UNSUPPORTED_CHARACTER` in `human_symbolic` scenes.
- `ABSTRACT_ENVIRONMENTS` set + `should_skip_environment_check()` — skips
  `ENVIRONMENT_MISMATCH` when Scene Analysis environment is abstract/internal
  and a real-world visual metaphor is standing in for it (correct practice).
- `run_validators()`/`StoryFidelityValidator.validate()` gained a
  `scene_category: str = ""` param (default preserves old behavior for any
  caller that doesn't pass it).
- 6 pre-existing tests in `tests/test_validators.py` that asserted the removed
  checks' old behavior were rewritten to assert those checks no longer fire.
  +14 new tests in `tests/test_validator_semantic_fix.py`.
- Full suite: 2767 passing (was 2753), same 1 pre-existing unrelated failure,
  1 skipped — no regressions.

## 2026-07-26 — Task 2.2: Retry Engine Reliability & Strict Structured Output
**Spec:** `docs/image-prompt/tasks/task-2.2-retry-engine-reliability.md`

Fixed the scene-planner root cause where two separate retry systems (inline
story-fidelity retry + a later batch "Retrying N failed prompt(s)" phase) fired
independently, didn't know about each other, and the batch phase always wrote
`"retry parse failed"` because its prompt/parser pair could never agree on a
format.

- **`video_core/providers/llm/*`:** `generate()` (base + all providers —
  openai_provider/deepinfra/groq/ollama/gemini) gained `json_mode: bool` and
  `json_schema: dict | None`, wired to `response_format={"type": "json_object"}`
  or strict `{"type": "json_schema", ...}` on the OpenAI-compatible providers;
  Gemini maps this to `response_mime_type`/`response_schema`.
- **`ytfactory/agents/nodes/scene_planner.py`:** batch retry phase deleted;
  replaced with a single inline per-scene generate → validate (deterministic +
  legacy LLM faithfulness) → structured-retry loop, capped at
  `scene_planner_max_retries`. Fixed an `UnboundLocalError` on `legacy_passed`
  that would have fired on every scene whose first attempt failed deterministic
  validation.
- **`ytfactory/images/validators.py`:** `HumanClassification.HUMAN_SYMBOLIC`,
  `SYMBOLIC_BODY_PART_EXCEPTION` (hands/feet/eyes in close-up don't count as a
  human-figure violation), `RETRY_RESPONSE_SCHEMA`, `parse_retry_response()`
  (handles raw/fenced/embedded JSON, logs exact `JSONDecodeError` position),
  `build_retry_prompt()` (single-scene strict-JSON retry request).
- **`ytfactory/agents/prompts/scene_planner.py`:** entity-extraction and
  scene-analysis prompts gained `human_symbolic` scene_category /
  `permitted_symbolic` human_requirement (philosophical/viewer-address
  narrations — "ancient teachers", "your hands" — get a symbolic human, not a
  false `no_human_allowed` flag) and an `animal_only` vs `abstract`
  disambiguation rule (incidental animal mentions ≠ animal-only shot).
- **`ytfactory/scenes/models.py`:** `FaithfulnessStatus` enum (`pass` /
  `failed` / `skipped`) replaces the old ad-hoc status strings.
- **`ytfactory/images/faithfulness_gate.py`** (new): `evaluate_faithfulness_gate()`
  — named to avoid colliding with the pre-existing, unrelated
  `ytfactory.retention.pre_render_gate` (a retention-scoring gate). Writes
  `scenes/faithfulness-gate.json`; never blocks the pipeline. Wired into
  `two_phase/pipeline.py::_write_phase1_report()` under the `faithfulness_gate`
  key in `phase1_report.json`.
- **New settings** (`ytfactory/config/settings.py`): `scene_planner_max_retries`
  (default 2), `scene_planner_json_mode` (default True),
  `scene_planner_strict_schema` (default False), `faithfulness_gate_fail_pipeline`
  (default False, reserved — gate is currently always non-blocking by design).
- **Tests:** +29 across `tests/test_json_mode_providers.py` and
  `tests/test_retry_engine_reliability.py` (parser edge cases, HUMAN_SYMBOLIC /
  body-part exception, entity-extractor mapping, gate pass/fail, no-batch-retry
  source check, provider `json_mode` wiring).
- **Known gap:** the per-scene retry loop is inline in `scene_planner_node`
  rather than a standalone function, so it's covered via its building blocks
  (parser/validator/gate/provider) rather than one end-to-end mocked run.
  Re-verifying real scenes 17/18/19/20/24 from the log in the spec doc against
  an actual project run was not done (needs a live pipeline run).
- **Pre-existing, unrelated bug found while regression-testing:**
  `tests/test_two_phase_pipeline.py::test_prep_only_requires_project_id` fails —
  `agents/runner.py` validates `pipeline_mode == "resume"` requires a
  `project_id` but has no equivalent check for `pipeline_mode == "prep_only"`,
  so it falls through into a real (slow, live-API) pipeline run instead of
  raising `ValueError` early. Predates this task (last touched in the two-phase
  workflow commit); not fixed here — out of scope.
- **Concurrency note:** another tool/session was independently implementing
  the same spec in `validators.py`/`scene_planner.py` while this work was in
  progress; per explicit user direction ("take over and continue"), their
  `HUMAN_SYMBOLIC`-enum design was adopted as source of truth and finished
  (missing `logger`/`build_visual_prompts_prompt` imports fixed, dead
  leftover class attrs removed).

## 2026-07-24 — Renderer CFR enforcement and remediation data-reconstruction fixes
- `video/ffmpeg.py` `render_continuous()`: added `-r` and `-s` encoding options so the final MP4 is forced CFR at the target frame rate and resolution, eliminating potential VFR judder from concat-joined scene segments.
- `video/pipeline.py`: brand-card asset scenes now render correctly — added `"brand_card"` to the `scene_type in ("asset", "brand_card")` check so the configured brand asset path is consumed instead of looking for a generated PNG.
- `review/remediation/engine.py`: fixed `_rca_proxy` / `_efl_proxy` to reconstruct `RCAIssue` and `FeedbackItem` objects from serialised dicts instead of returning empty proxies, so remediation actions are built from actual review failures rather than empty lists.
- `review/rca/analyzers/rendering.py`: added REND_007 mapping (`missing_brand_card`) so the RCA engine produces actionable remediation instead of falling back to `_unknown_issue` with confidence=0.
- `review/scoring/scorers/rendering.py`: added REND_007 (10 pts) to `_POINTS` so a missing brand card lowers the quality score and blocks the quality-threshold early-exit path.

## 2026-07-24 — Motion fixes: zoom visibility, smooth interpolation, duration coverage
- `ffmpeg_filters.py` / `ffmpeg.py`: changed zoompan `d=total_frames` to `d=1` so the zoom/pan expression is evaluated every output frame — eliminates discrete-step motion and ensures smooth continuous movement.
- `ffmpeg_filters.py` `_t_factor()`: normalized to `on / (total_frames - 1)` so t reaches exactly 1.0 on the final frame, ensuring `end_scale` is fully reached.
- `profiles.py`: increased scale ranges — small now 1.0→1.10, medium 1.0→1.15, large 1.0→1.22 (cinematic). Premium reaches 1.25. Drift amounts increased 15-20%.
- `profiles.py`: removed `"static"` from all `_ACCEPTABLE_MOTIONS` entries; `get_acceptable_motions()` default changed from `["static"]` to `["drift"]` so the rebalancer never reintroduces static motion.
- Per-scene motion diagnostics verified: all scenes have continuous non-static motion; zoom deltas visible (≥5%); easing smooth; no premature static fallback.

## 2026-07-24 — Bugfix: opening-line leak, missing brand card, static/jerky motion
- `build_pass2_prompt()`: opening-line welcome_block is now correctly omitted when `opening.enabled=false` (was checking `welcome is None` but caller always passes a string).
- `pipeline.py`: added `_strip_disabled_opening_line()` to remove matching paragraphs from final `script.md` before downstream stages.
- `scene_planner.py`: added `_is_opening_scene()` and `_OPENING_TRIGGERS`; `_mark_asset_scenes()` now removes *all* closing/opening-matching scenes and unconditionally appends a new `scene_type="brand_card"` final scene with correct `asset_id`/`asset_path` from `brand_config.yaml`.
- `_write_script_segments()`: when `opening.enabled=false`, paragraphs matching the disabled opening are tagged `is_opening_line=true` in `script-segments.json`.
- `motion.py`: removed static fallback — default motion for unmapped emotions is now `("drift","small")`; unrecognized motion types fall back to drift rather than static; asset motion unrecognized animations fall back to `slow_zoom` instead of static.
- `motion.py`/`profiles.py`: added `reference_duration_seconds` and `max_drift_scale_factor` to `ProfileConfig`; drift magnitude now scales with scene duration so longer scenes maintain continuous motion.
- `profiles.py`: default `Settings.render_profile` changed from `"balanced"` to `"cinematic"`; `_BALANCED_MAP`/`_CINEMATIC_MAP` updated so `peace`/`revelation` map to `drift` instead of `static`.
- `image.py` (ImageValidator): `IMG_007` upgraded from WARNING to FAIL (blocking); added exemption for `hold_required=true` scenes.
- `rendering.py` (RenderingValidator): added critical `REND_007` — final scene must be `scene_type="brand_card"` with correct asset path.
- Tests: +14 new tests (13 bugfix + 1 early-return regression), 4 updated. Full suite: 2644 passed, 1 skipped, 0 unrelated failures.
- E2E verification: all 5 checks pass (no opening line in script, final scene brand_card, no static scenes, brand card narration clean, REND_007 pass).

## 2026-07-13 — Chapters capped at 10 (logical scene-merge); CTA overlay enabled
`ChaptersGenerator` now caps output at `publish_max_chapters` (default 10), merging adjacent scenes into even contiguous groups when there are more natural chapter boundaries than the cap. Never pads short videos up to the cap. Minimum chapter duration `publish_min_chapter_seconds` (default 10s, YouTube's own rule) is enforced even if it means fewer than the cap. New settings: `publish_max_chapters`, `publish_min_chapter_seconds`. CTA overlay enabled in `config/brand_config.yaml` (`cta_overlay: enabled: true`).

## 2026-07-13 — cinematic/ promoted to video_core (commits 4742590, 925f4f7, a0bd568)
Moved motion.py, transitions.py, profiles.py, effects.py, config.py from
ytfactory/cinematic/ to video_core/cinematic/ — zero prior Settings/
workspace coupling, pure relocation. Extracted FFmpegRenderer._vf_spatial
and _t_factor into standalone video_core.cinematic.ffmpeg_filters.
build_zoompan_filter() — zero behavior change, FFmpegRenderer now
delegates to it. Resolves AS-002 (agentic/sequential renderer
duplication) — both paths now import from one canonical location.
Test count unchanged: 2165 passing, 0 failing.

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

## 2026-07-21 — TTS Analytics & Cost Tracking + Pipeline Quality Gate
**TTS Analytics & Cost Tracking** (`src/video_core/providers/tts/analytics/`):
- `TTSAnalyticsRecord` — per-request telemetry: scene_id, provider, model, voice, text, characters, words, sentences, cache_hit, retry_count, latency_ms, request_timestamp, output_bytes, audio_duration, estimated_credits, estimated_cost, provider_response_metadata
- `TTSAnalyticsCollector` — accumulates provider metrics (`TTSProviderMetrics`: cache_hit_rate, avg_latency_ms, retry_rate), per-video summaries (`TTSVideoSummary`: providers_used, models_used, voices_used, scene_summaries), duplicate detection, cost optimization reports
- `ProviderPricingConfig` / `TTSProviderPricing` — configurable pricing abstraction: credits_per_character, credits_per_request, usd_per_credit. Cartesia pricing loaded from `SharedSettings` fields (`cartesia_credits_per_character`, `cartesia_credits_per_request`, `cartesia_usd_per_credit`) or `TTS_PRICING_*` env vars. Never hardcoded.
- `count_text()` — character/word/sentence counting utility
- Per-scene log: `Scene 07 | Provider: cartesia | Model: sonic-3.5 | Voice: Nolan | Characters: 184 | Words: 31 | Duration: 11.2s | Cache Hit: true | Retries: 0 | Latency: 1.84s | Estimated Credits: XXX | Estimated Cost: $0.00XX`
- Per-video TTS SUMMARY block after generation: Scenes, Requests, Characters, Words, Total Audio Duration, Average Scene Duration, Average Characters, Cache Hits, Cache Misses, Cache Hit %, Retries, Average Latency, Estimated Credits, Estimated Cost, Providers, Models, Voices
- New settings: `tts_analytics_enabled`, `tts_cost_tracking_enabled`, `tts_log_per_scene`, `tts_summary_enabled`, `tts_verify_cache` (all default true)

**Pipeline Quality Gate:** `PipelineAbort` exception in `ytfactory.shared.pipeline_status`. Critical gates raise `PipelineAbort(stage, reason)` when `STOP_ON_QUALITY_GATE_FAILURE=true` (default). Downstream stages skipped; concise abort summary printed. Wired in `DocumentaryScriptEnhancerPipeline` for:
- Narrative Score below 8.5 after max iterations → stage `documentary_enhancer_pass2`
- Final validation failure (scripture missing, coverage too low) → stage `documentary_enhancer_final`
- Duration out of tolerance after Pass 3 correction → stage `documentary_enhancer_duration`
- `BuildPipeline.run()` and `run_pipeline()` catch `PipelineAbort` and exit gracefully with skipped stages list.

**Cache fix:** `TTSCache.make_key()` now includes `emotion` and `sample_rate` in key. Cartesia provider logs actual `cache_hit=true/false` instead of `pending`.

**Tests:** +18 new TTS analytics tests in `tests/test_tts_analytics.py`; +3 pipeline quality gate tests in `tests/test_documentary_script_enhancer.py`.

## 2026-07-20 — Visual Intelligence Architecture (Phases 2–6)
New `src/video_core/visual_intelligence/` package:
- **Phase 2 — Visual Intelligence Prompt Builder:** `PromptBuilder` consumes `VisualMetadata` and assembles provider-ready prompts via `PromptPackage`. Prompt assembly layers: Scene Description → Visual Profile → Era Rules → Environment → Narrative Role → Mood → Provider formatting. `PromptPackage` fields: final_prompt, negative_prompt, visual_profile, prompt_fingerprint, metadata_snapshot, assembly_report. Visual profiles for each era (ancient, historical, modern, symbolic, transitional) with positive/negative prompt fragments, lighting/architecture/materials/atmosphere/camera/color hints. Era behavior: ANCIENT injects historically authentic constraints and rejects anachronisms; HISTORICAL requires authenticity; MODERN allows technology; SYMBOLIC allows surreal/abstract; TRANSITIONAL allows intentional coexistence.
- **Phase 3 — Era-Aware Vision QA:** `VisualMetadata` domain model (era, narrative_role, environment, mood, visual_style, allow_modern_objects, reason, identities, is_populated). Era-aware prompt builder injects era-specific anachronism constraints, narrative-role hints, environment/mood validation blocks. Hand-anatomy verification block injected when `is_hand_focal()` returns True. New `VisionIssue` categories: anatomy, face, lighting, environment, artifact, cinematic, anachronism, historical_accuracy, mood, composition, camera, text, style. All vision providers extended with `visual_metadata` and `prompt_package` parameters.
- **Phase 4 — Intelligent Prompt Remediation Engine:** `RemediationEngine`, `RemediationPackage`, `RemediationStrategyEngine`. `RemediationPackage` fields: original_prompt, remediated_prompt, remediation_reason, issues_fixed, preserved_constraints, added_constraints, removed_constraints, prompt_diff, remediation_strategy, attempt_number, era, confidence, highest_severity. Era-aware remediation library selects constraints based on era and issue category. Confidence-based escalation: LOW→minimal_edit, MEDIUM→strengthen_constraints, HIGH→significant_remediation, CRITICAL→full_regeneration_hint. Wired through `ImageRemediationOrchestrator`.
- **Phase 5 — Visual Intelligence Analytics:** `AnalyticsCollector`, `DashboardModel`, `BenchmarkResult`, `PromptAnalytics`, `CostSummary`, `QualityMetrics`, `ProviderMetrics`. JSON/Markdown exporter; report generator (daily/weekly/monthly). Tracks credits per scene/video/month, cost per video/minute, characters per minute, average latency, cache hit %, retry %, provider/voice usage.
- **Phase 6 — Character/Object Consistency Engine:** `VisualIdentity` (identity_id, identity_type, display_name, description, canonical_attributes, reference_image_paths, created_at, updated_at). `IdentityRegistry` — central registry of visual identities loaded from config. `SceneMemory` — tracks identity usage across scenes. `PromptEnricher` — adds identity continuity hints to prompts from SceneMemory. `ContinuityValidator` — validates identity drift (attribute mismatches). Consistency reports in JSON/Markdown.

**Vision provider interface extended:** `review()` now accepts `visual_metadata: VisualMetadata | None` and `prompt_package: PromptPackage | None`. All providers updated (Gemini, local, HF, llama.cpp, mock, throttled).

## 2026-07-18 — ADR-0015 Human Subject Quality Gate + TTS/vision fixes
**ADR-0015 Human Subject Quality Gate** (`docs/image-prompt/ADR-0015_Human_Subject_Quality_Gate.md`):
- If human occupies >20% of frame or is primary storytelling subject → mandatory Human QA required
- Reject if: missing/extra body parts, broken anatomy, impossible pose, deformed face, wrong age/gender/ethnicity/emotion if specified, subject cropped incorrectly
- Mandatory Hand QA if hands visible: reject for incorrect finger count, fused/missing/duplicate fingers, deformed thumb, distorted palm, unnatural wrist, impossible finger joints
- Clothing validation: if clothing specified in prompt, it is mandatory
- Prompt compliance: verify subject, clothing, pose, camera angle, environment, emotion, key props
- Recommended pipeline: Generate → Overall Quality Review → Human QA → Hand QA → Prompt Compliance Review → Approve
- New review rules in `review/validation/rules/human.py`: HUM_004 (anatomy specialist), HUM_005 (subject criticality — eyes/face must be visible and sharp for close-up/human-focal scenes)

**TTS chunking fix:** `batch_sentences()` in `src/video_core/providers/tts/infra.py` now uses punctuation-based splitting instead of newline-based — removes mid-phrase pauses in narration.

**llama.cpp SIGSEGV fix:** `set_rows()` guard + SIGABRT handler in `src/video_core/providers/vision/local.py` for Qwen2.5-VL-3B.

## 2026-07-17 — ADR-0014 Pipeline Progress Reporting & Status Tracking
(`docs/adr/ADR-0014_Pipeline_Progress_Reporting_Status_Tracking.md`)
- `PipelineStatusWriter` in `ytfactory.shared.pipeline_status` — atomic `pipeline-status.json` writes + terminal progress
- Stage lifecycle: `stage_start()` / `stage_progress()` / `stage_retry()` / `stage_complete()` / `stage_fail()`
- Progress types: Determinate (counters), Indeterminate (spinner), Iterative (retry count + score)
- ContextVar-based writer isolation — safe across threads/tasks
- `activate_writer()` context manager
- Used by `BuildPipeline` and all sub-pipelines
- Pipeline stages tracked: Research → Light Normalization → Documentary Enhancer Pass 1/2 → Scene Planning → Image Generation → Image QA → Image Regeneration → TTS → Subtitle Generation → Subtitle Editing → Background Music → Scene Rendering → Video Merge → CTA Overlay → Final Packaging

## 2026-07-17 — ADR-0013 Subject Criticality & Human Anatomy Specialist Review
(`docs/image-prompt/ADR-0013_Subject_Criticality_Validation.md`)
- If primary storytelling subject is human hand/face/eye/body/gesture → must be anatomically realistic
- Hand validation checklist: exactly five fingers, natural thumb attachment, correct palm proportions, natural wrist transition, correct finger joint placement, no fused/duplicate/stretched fingers, natural resting pose, photorealistic skin texture
- Review strategy: Generation → Overall Image Review → Subject Specialist Review → Approve only if BOTH pass
- Any hand/face/anatomy failure → reject image, regenerate automatically, re-run validation

## 2026-07-17 — ADR-0012 Religion-Agnostic Presentation Policy
(`docs/script/ADR-0012-religion-agnostic-presentation.md`)
- **What gets dropped:** Tradition/religion names (Vedanta, Advaita Vedanta, Hindu philosophy, Sanatan Dharma), named texts (Bhagavad Gita, Upanishads, Puranas), untranslated Sanskrit terms presented as Sanskrit
- **What stays:** Philosophy and teaching exactly as is; named ancient teachers/wisdom figures presented as historical wisdom figures; universal framing devices ("the sages," "ancient teachers," "ancient wisdom"); story/analogy material
- **Source Attribution Ladder:** (1) Named historical teacher when source provides one (e.g. "Adi Shankaracharya taught..."), (2) Generic ancient attribution ("One ancient teaching says..."), (3) No attribution when neither adds value
- **Script title heading:** H1 heading should NOT be narrated or subtitled — it's a structural label, not spoken content
- **Publish stage rules:** Title/description/hashtags must not include tradition/text names; Sources section genericized; hashtags replaced with universal equivalents
- `religion_agnostic.check()` scans final script for policy violations
- Validation: term-list check for tradition names, named texts, Sanskrit-term detection

## 2026-07-17 — ADR-0011 Two-Pass Cinematic Script Enhancer
**⚠ SUPERSEDED 2026-07-28** — `DocumentaryScriptEnhancerPipeline` is archived (not deleted) and no
longer wired into any active pipeline path. Replaced by the whole-cloth `ComposerPipeline`; see
`## 2026-07-28 — Composer replaces enhancer + Structural Retention Pass` above. Kept below for
history only — do not treat as the current script-generation mechanism.
(`docs/script/ADR-0011-documentary-script-enhancer-upgrade.md`)
- `DocumentaryScriptEnhancerPipeline` renamed from `ScriptEnhancerPipeline` (backward-compatible alias preserved)
- **Pass 1 (temp=0.4): Faithful Enhancement** — fidelity gate before retention optimization. Goals: preserve philosophy, emotional intent, stories, analogies, historical references, humor, speaker personality; improve clarity and flow. Must NOT optimize for engagement at cost of fidelity.
- **Pass 2 (temp=0.7): Viewer Retention Optimization** — optimize for long-form YouTube. Goals: stronger hook, better transitions, improved storytelling, increased curiosity, emotional pacing, cinematic narration, memorable reflections.
- **10 Viewer Retention Rules:** (1) Prefer stories over abstract philosophy, (2) Avoid long uninterrupted philosophical exposition, (3) Preserve cinematic pacing (short sentences, intentional pauses), (4) Delay branding (never interrupt opening hook), (5) Maintain curiosity (raise question, delay answer, reward later), (6) End chapters with momentum (avoid complete conclusions), (7) Create memorable lines, (8) Reduce unnecessary repetition (distinguish rhetorical from spoken-language repetition), (9) Preserve speaker voice, (10) Do not rewrite for the sake of rewriting.
- **Narrative Score self-assessment:** Hook / Story Density / Curiosity / Emotional Rhythm / Accessibility / Overall — threshold 8.5/10. If Overall < 8.5, continue improving. Self-assessment is internal guide, not downstream gate.
- **Validation Criteria:** Objective checks (scripture exact-match, no unattributed factual claims, coverage check, Pass 1 gate) are binding. Subjective checks (story density, narrative variety, curiosity, quote density, emotional rhythm, cinematic breathing room, audience accessibility, documentary test) are review guides, not blocking gates.
- **Fabrication Guardrail:** New illustrative material must be drawn from source, or generic/explicitly hypothetical ("imagine someone who..."), never presented as verified fact.
- **Scripture Protection:** Hard constraint across both passes — any scripture/Sanskrit/direct quotation span must be reproduced byte-for-byte. If uncertain, default to protected.
- **Priority Order:** Preserve meaning → philosophy → speaker intent → stories/analogies → viewer retention → storytelling → cinematic narration → English. Fidelity always wins over retention.
- **Settings:** `target_minutes` (default 7), `DURATION_TOLERANCE_MINUTES=1`, `NARRATION_WPM=130`

## 2026-07-17 — ADR-0010 Light Normalization + Enhancer Rename
(`docs/script/ADR-0010-light-normalization-stage.md`, `docs/script/ADR-0010-addendum.md`)
- `LightNormalizationPipeline` — new pre-script stage in `BuildPipeline`. LLM call at temperature=0 with preserve-first prompt.
- Scripture protection via **pre-extraction**: Devanagari/Kannada/Tamil/etc. Unicode-range spans and `<scripture>...</scripture>` markers replaced with `{{SCRIPTURE_N}}` placeholders BEFORE the LLM sees the text, restored byte-for-byte afterward. Stronger than spec — removes risk class entirely.
- `NormalizationValidator` — four automated checks: change-ratio bound (15% threshold), scripture placeholder match, paragraph-order invariant, no-new-content (Jaccard token overlap).
- **Fallback behavior:** On validation failure, falls back to original (unnormalized) transcript and continues pipeline — more conservative than halting. Deviation from ADR spec recorded in addendum.
- **Open follow-ups (from addendum):** (1) Change-ratio threshold 15% vs ADR's "low single-digit" — confirm if calibrated or placeholder; (2) Span-level ambiguity flagging — status unconfirmed, may be gap; (3) Scripture detection coverage for untagged romanized Sanskrit without diacritics — test against real ASR output; (4) Option 2 (STT input path) correctly deferred.
- `DocumentaryScriptEnhancerPipeline` — renamed from `ScriptEnhancerPipeline` (backward-compatible alias preserved)
- Pipeline wiring in both `run()` and `run_incremental()`
- CLI: `ytfactory normalize <id>` and `--script` import on create
- 24 new tests

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
LangGraph graph in `src/ytfactory/agents/`. Entry: `run_pipeline()` in `agents/runner.py`.  
`--resume --project <id>` skips the LangGraph graph entirely → routes to `BuildPipeline.run_incremental()`.

**⚠ Updated 2026-07-28** — `script_enhancer`/`structural_retention` nodes removed from the active
graph (archived; see `## 2026-07-28 — Composer replaces enhancer...` above). Current nodes (per
`agents/graph.py`, verified against actual `add_edge`/`add_conditional_edges` calls): START
→(`_route_entry`: source_url → path → neither)→ `acquire_audio` **or** `composer` **or**
`research_agent`. YouTube-URL path: `acquire_audio` → `transcribe` → `translate` →
`human_review_base_script` → `composer`. Research path: `research_agent` → `script_writer` →
`human_review_script` → `composer`. All three converge at `composer` → `editorial_qa` →
`human_review_final_script` → `scene_planner` → `pre_render_gate` → `human_review_scenes`
→(`_dispatch_scenes`, fan-out)→ `generate_scene_assets` (per-scene parallel)
→(`_route_after_assets`)→ `video_renderer` → `video_concatenator` → `cta` → `quality_review`
→(`_route_after_review`)→ `remediation` or `publish` →(`_route_after_remediation`)→ `publish` → END.

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
│   │   └── tts/
│   │       └── analytics/  # TTS cost tracking (2026-07-19)
│   ├── models/          # LAMM: manager, registry, bundle, capabilities
│   ├── domain/          # LLMResponse, SearchResult, ImageRequest, VisualMetadata
│   ├── config/          # SharedSettings (Phase 1, 2026-07-12)
│   ├── cinematic/       # MotionPlanner, TransitionPlanner, profiles, effects,
│   │                    # ffmpeg_filters (promoted 2026-07-13; usable by any
│   │                    # factory, no shim needed)
│   └── visual_intelligence/  # Phases 3-6 (2026-07-20)
│       ├── analytics/   # AnalyticsCollector, DashboardModel, exporter
│       ├── consistency/ # VisualIdentity, IdentityRegistry, SceneMemory
│       ├── profiles/    # VisualProfile registry
│       ├── prompt_builder.py
│       └── prompt_package.py
│
└── ytfactory/           # unchanged product code — review, publish, bgm,
                         # branding, agents, build, scenes, providers/tts/pacing/,
                         # domain/project.py, config/, everything else
```

**Layering rule:** `video_core` must not import from `ytfactory`. Enforced by `scripts/check_layering.py`. `ytfactory.config.settings` was resolved by Phase 1. **One remaining Bucket-C exception:** `ytfactory.shared.constants` (`WORKSPACE_DIR`) — deferred to Phase 2.  
**`video_core.cinematic`** — `MotionPlanner`, `TransitionPlanner`, `build_zoompan_filter` are clean `video_core` imports; any factory can use them directly with no shim (AS-002 resolved).

---

## Current Provider Stack (live `.env`, verified directly — as of 2026-07-26)

| Provider type | Setting | Current value |
|---|---|---|
| LLM | `LLM_PROVIDER` | `anthropic` → `OpenAICompatibleProvider`, routed via `ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1` (OpenRouter proxy, not the official Anthropic API) |
| LLM model | `ANTHROPIC_MODEL` | `deepseek/deepseek-v3.2` (confirmed both in `.env` and in this session's live pytest logs) |
| Search | `SEARCH_PROVIDER` | `tavily` |
| Image | `IMAGE_PROVIDER` | `huggingface` (multi-tier: FLUX.1-schnell / Qwen-Image / FLUX.1-dev via `IMAGE_MODEL_TIER{1,2,3}_ID`) |
| TTS | `TTS_PROVIDER` | `cartesia` (CartesiaTTSProvider — premium cloud TTS; **not** Kokoro) |
| TTS model/voice | `CARTESIA_MODEL` / `CARTESIA_VOICE_ID` | `sonic-3.5` / Nolan (`65209f8e-6140-4a20-b819-3cc2e21da19b`), speed `0.88`, emotion `contemplative`, sample rate `48000`, timeout `90`, max_chars `2500` |
| Vision | `VISION_REVIEW_PROVIDER` | `huggingface` (`HF_VISION_MODEL=Qwen/Qwen2.5-VL-32B-Instruct`, `HF_VISION_PROVIDER=auto`) — **not** the `local` llama.cpp path; `IMAGE_REVIEW_ENABLED=false` (gate is currently off) |
| WhisperX | `WHISPERX_ENABLED` | `false` (`WHISPERX_MODEL=base` reserved, unused while disabled) |
| WhisperX device | `WHISPERX_DEVICE` | `cpu` |
| Resolution | `IMAGE_WIDTH/HEIGHT` | `1280×720` |
| BGM | (not set in `.env` → falls back to `Settings` default `false`) | ducking tuned via `BGM_VOLUME=0.20`, `BGM_DUCK_FLOOR=0.07`, `BGM_DUCK_THRESHOLD=0.025`, `BGM_DUCK_RATIO=3.0`, `BGM_NARRATION_LEVEL_LUFS=-18.0` when enabled |
| Render profile | `RENDER_PROFILE` | `cinematic` |

Local/mock vision providers (`local` + `qwen2_5_vl_3b`/`minicpm_v2_6`, or `mock`) remain valid, implemented alternatives — they are simply not what the live `.env` currently selects.

**Provider factory pattern:** business logic calls `get_llm_provider(settings)` / `get_image_provider(settings)` / `get_tts_provider(settings)` — never imports a concrete provider directly.

| Provider type | Base class | Implementations | Setting key |
|---|---|---|---|
| LLM | `video_core.providers.llm.base` | Gemini, Anthropic (OpenAI-compat), Groq, Ollama | `LLM_PROVIDER` |
| Search | `video_core.providers.search.base` | Tavily | `SEARCH_PROVIDER` |
| Image | `video_core.providers.image.base` | HuggingFace, Gemini | `IMAGE_PROVIDER` |
| TTS | `video_core.providers.tts.base` (pacing engine stays at `ytfactory.providers.tts.pacing`) | Kokoro, Edge TTS, Cartesia | `TTS_PROVIDER` |
| Vision | `video_core.providers.vision.base` | Gemini, Local (Qwen2.5-VL/llama.cpp), HuggingFace, llama.cpp, Mock | `VISION_REVIEW_PROVIDER` |

`get_<type>_provider()` factory functions moved with their base classes — call sites unchanged, only import paths changed.

---

## All Implemented V1 Specs (chronological)

### 1. VIDEO_QUALITY_REVIEW_ENGINE_V1
Multi-layer quality gate in `src/ytfactory/review/`. Runs after `ytfactory render`.

- **Layer 1 — Stage checks** (`review/stages/`): asset_integrity, timeline, content, production_quality
- **Layer 2 — Validation rules** (`review/validation/`): originally 9 validators (script, narration, subtitle, image, human, motion, audio, rendering, story); grew to **12** with the addition of bgm, vision_review, cta (see §14, §"Key Invariants" below — `ValidationRunner runs 12 validators` is the current, final count). Each rule: structured `ValidationResult` with rule ID, severity, evidence, confidence, `responsible_engine`.
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

**ChaptersGenerator** (`publish/generators/chapters.py`):  
- Produces at most `publish_max_chapters` (default 10) chapters; adjacent scenes merged into balanced contiguous groups via `_make_chapter_groups()`.  
- Short videos get fewer chapters — never padded up to the cap.  
- `publish_min_chapter_seconds` (default 10s, YouTube's rule) enforced post-merge; further merges if needed (may produce fewer than cap).  
- `ChaptersGenerator(settings=None)` — lazy `Settings()` read if no settings passed; `getattr(..., default)` used throughout for mock safety.

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

**CTA overlay** (`config/brand_config.yaml → cta_overlay:`): visual call-to-action overlay distinct from the narrated `cta:` text block. **Currently enabled** (`enabled: true`, as of 2026-07-13). Template: `atma`, timing: `contextual`, duration: `6s`. BGM secondary duck: `−4 dB`. Config-driven — flip `enabled: false` to disable without code changes.

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
**Current (final) state: four entries** — `whisperx`, `silero_vad`, `qwen2_5_vl_3b`, `minicpm_v2_6`. All have `auto_download: false` by default.
- Lazy models (`whisperx`, `silero_vad`): no `hf_repo` — skip download entirely; return VERIFIED immediately
- `qwen2_5_vl_3b` (the **active default** vision model, see §14 Settings and Key Invariants below): `hf_repo: "ggml-org/Qwen2.5-VL-3B-Instruct-GGUF"`, `runtime: llama_cpp`
- `minicpm_v2_6` (kept as an A/B alternative, not the default): `hf_repo: "openbmb/MiniCPM-V-2_6"`, `min_disk_gb: 10`, requires torch/transformers/pillow

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
- `qwen2_5_vl_3b`: `runtime: llama_cpp`, active default vision model (see §14)
- `minicpm_v2_6`: `runtime: transformers`, `capabilities: [image_review, structured_json]`, `bundle.artifacts.text_model: {file: "."}` — kept as A/B alternative, not the default

**Test count:** +72 new tests in `tests/test_model_bundle.py` → **1929 total**

---

### 14. IMAGE_REVIEW_PIPELINE_V1
**Spec:** `docs/review/IMAGE_REVIEW_PIPELINE.md`  
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
├── local.py         # LocalVisionProvider — lazy-loads via LAMM; Qwen2.5-VL-3B .chat() API
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
IMAGE_REVIEW_ENABLED=true           # Settings class default (code); live .env sets it to false — gate is OFF in current practice
VISION_REVIEW_PROVIDER=local        # "local" | "mock" | "gemini" | "huggingface"; live .env uses "huggingface" (HF_VISION_MODEL=Qwen/Qwen2.5-VL-32B-Instruct)
VISION_REVIEW_LOCAL_MODEL=qwen2_5_vl_3b   # active default when VISION_REVIEW_PROVIDER=local
IMAGE_REVIEW_MIN_SCORE=90
IMAGE_REVIEW_CONFIDENCE=80
IMAGE_REVIEW_MAX_ATTEMPTS=3
IMAGE_REVIEW_AUTO_REMEDIATE=true
IMAGE_REVIEW_DEBUG=false
```

#### Key Invariants
- `image_review_enabled=true` is the `Settings` class **code** default → `_build_review_engine()` creates vision engine at runtime; the live `.env` explicitly overrides this to `false`, so the gate does not run in current practice — check the real `.env` before assuming it's active
- Default local vision model is `qwen2_5_vl_3b` via **config only** — never hardcoded in business logic (this only applies when `VISION_REVIEW_PROVIDER=local`; the live `.env` instead uses `VISION_REVIEW_PROVIDER=huggingface`)
- `_regenerate()` passes `seed=None` → new random seed each attempt
- ValidationRunner now runs 12 validators (was 10) — added VisionReviewValidator and CTAValidator
- Test count: 20 new (test_vision_provider.py) + 26 new (test_image_review_engine.py) = 46 new tests

---

### 15. VISUAL_INTELLIGENCE_LAYER_V1
**Spec:** `docs/video/PHASE_3_ERA_AWARE_VISION_QA.md`, `docs/video/PHASE_4_INTELLIGENT_PROMPT_REMEDIATION_ENGINE.md`, `docs/video/PHASE_5_VISUAL_INTELLIGENCE_ANALYTICS.md`, `docs/video/PHASE_6_CHARACTER_OBJECT_CONSISTENCY_ENGINE.md`  
**New files:** `src/video_core/visual_intelligence/` package (analytics, consistency, profiles, prompt_builder.py, prompt_package.py, models.py)  
**Modified:** `src/video_core/providers/vision/base.py`, all vision providers, `src/ytfactory/images/review_engine.py`, `src/ytfactory/workflow/image_remediation_orchestrator.py`, `src/ytfactory/agents/nodes/scene_assets.py`

#### VisualMetadata domain model
`VisualMetadata` (Pydantic): era (ANCIENT|HISTORICAL|MODERN|SYMBOLIC|TRANSITIONAL), narrative_role (STORY|ANALOGY|METAPHOR|EXPLANATION|ESTABLISHING|CTA), environment, mood, visual_style, allow_modern_objects, reason, identities, is_populated.

#### Era-aware vision QA
`build_era_aware_prompt()` in `vision/base.py` injects era-specific anachronism constraints, narrative-role hints, environment/mood validation blocks into the review prompt. Hand-anatomy block injected when `is_hand_focal()` returns True.

#### PromptPackage
Structured output from Prompt Builder: final_prompt, negative_prompt, visual_profile, prompt_fingerprint, metadata_snapshot, assembly_report. Stored in scene dict as `_prompt_package` for downstream consumption.

#### RemediationEngine
`RemediationPackage` with original_prompt, remediated_prompt, issues_fixed, preserved/added/removed_constraints, prompt_diff, remediation_strategy, attempt_number, era, confidence, highest_severity. Era-aware remediation library selects constraints based on era and issue category.

#### Analytics
`AnalyticsCollector` accumulates `AnalyticsRecord` per scene; builds `DashboardModel` with provider comparison, quality trends, era trends, top failure categories, cost summary. JSON/Markdown export.

#### Consistency Engine
`VisualIdentity` (character/object/animal/building/environment/symbol), `IdentityRegistry`, `SceneMemory`, `PromptEnricher`, `ContinuityValidator`. Consistency reports in JSON/Markdown.

---

### 16. TTS_ANALYTICS_AND_COST_TRACKING_V1
**Spec:** `docs/tts/TTS_ANALYTICS_AND_COST_TRACKING_V1.md`  
**New files:** `src/video_core/providers/tts/analytics/` (models.py, collector.py, pricing.py, text_counter.py, __init__.py), `tests/test_tts_analytics.py`  
**Modified:** `src/video_core/providers/tts/cartesia.py`, `src/video_core/providers/tts/factory.py`, `src/video_core/providers/tts/infra.py`, `src/ytfactory/voice/pipeline.py`, `src/video_core/config/shared_settings.py`

#### TTSAnalyticsRecord
Per-request telemetry: scene_id, provider, model, voice, text, characters, words, sentences, cache_hit, retry_count, latency_ms, request_timestamp, output_bytes, audio_duration, estimated_credits, estimated_cost, provider_response_metadata.

#### ProviderPricingConfig
Configurable pricing abstraction — never hardcode provider pricing. `TTSProviderPricing(provider_name, credits_per_character, credits_per_request, usd_per_credit)`. Cartesia pricing loaded from `SharedSettings` fields or `TTS_PRICING_*` env vars.

#### TTSAnalyticsCollector
Accumulates `TTSAnalyticsRecord`s; computes `TTSProviderMetrics` (cache_hit_rate, avg_latency_ms, retry_rate) and `TTSVideoSummary` (per-video totals, provider/model/voice usage, scene summaries). Methods: `duplicate_detection()`, `cost_optimization_report()`.

#### Cartesia integration
`CartesiaTTSProvider` accepts optional `analytics: TTSAnalyticsCollector`; records analytics after synthesis. `TTSCache.make_key()` includes emotion and sample_rate. Logs actual `cache_hit=true/false`.

#### VoicePipeline integration
Per-scene TTS log after synthesis; per-video TTS SUMMARY block after pipeline completes. New settings: `tts_analytics_enabled`, `tts_cost_tracking_enabled`, `tts_log_per_scene`, `tts_summary_enabled`, `tts_verify_cache` (all default true).

#### Tests
+18 new tests in `tests/test_tts_analytics.py`: text counting, pricing estimation, collector metrics, video summary, cache hit rate, cost optimization report, duplicate detection, cache verification.

---

### 17. PIPELINE_QUALITY_GATE_V1
**Spec:** `docs/pipeline/PIPELINE_QUALITY_GATE_V1.md`  
**New files:** none (exception added to existing `ytfactory.shared.pipeline_status`)  
**Modified:** `src/ytfactory/shared/pipeline_status.py`, `src/ytfactory/script_enhancer/pipeline.py`, `src/ytfactory/build/pipeline.py`, `src/ytfactory/agents/runner.py`, `src/video_core/config/shared_settings.py`, `tests/test_documentary_script_enhancer.py`

#### PipelineAbort exception
`PipelineAbort(stage, reason)` in `ytfactory.shared.pipeline_status`. Carries failing stage name and human-readable reason. Caught by `BuildPipeline.run()` and `run_pipeline()` to produce concise abort summary.

#### Critical quality gates
- Documentary Enhancer: Narrative Score below threshold after max iterations
- Documentary Enhancer: Final validation failure (scripture missing, coverage too low)
- Documentary Enhancer: Duration out of tolerance after Pass 3 correction
- Scene planning failure
- Image generation exhausted retries
- Vision QA exhausted retries
- TTS generation failure
- Rendering failure
- Quality review FAIL after remediation

#### Abort behavior
When `STOP_ON_QUALITY_GATE_FAILURE=true` (default): raise `PipelineAbort`, skip all downstream stages, mark current stage failed in pipeline-status.json, print concise summary with skipped stages. When `false`: preserve old behavior (continue despite failures).

#### Tests
+3 new tests in `test_documentary_script_enhancer.py`: abort on low narrative score (enabled), no abort when disabled, abort on final validation failure.

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
- **Settings split (Phase 1):** `ytfactory.config.Settings` now inherits `video_core.config.SharedSettings`. Shared fields (API keys, provider selectors, model names, kokoro/a1111 provider config, `tts_auto_retry/max_retries`, `tts_analytics_*`, `stop_on_quality_gate_failure`) live in `SharedSettings`; pipeline/quality/content fields stay in `Settings`. All existing `settings.<field>` call sites are unchanged. Both classes load from the same `.env` file — no `.env` change needed. One remaining Bucket-C layering exception: `ytfactory.shared.constants` (WORKSPACE_DIR, tracked for Phase 2).
- **No feature pipeline may download/manage models directly** — all model lifecycle routes through `LocalAIModelManager` (LAMM).
- `force=True` on a lazy model (no `hf_repo`) routes to `_verify_from_cache()`, NOT `_download_and_verify()` — prevents `snapshot_download("")` ValueError.
- **Capability contract:** call `manager.validate_capabilities(model_name, required)` before loading. Returns `[]` on success; non-empty means `MISSING_CAPABILITY(cap)` — treat as pre-condition failure.
- **`entry.bundle` is always non-None after registry parse** — `_parse_bundle()` creates a synthetic minimal bundle when no explicit `bundle:` section exists.
- **Dockerfile uses `COPY config/ config/`** — `models-registry.yaml` and `brand_config.yaml` are baked in at `/app/config/`. Never use `COPY brand_config.yaml*` from root (that file doesn't exist; `config/` is the canonical location).
- **`model_bootstrap.py` uses `_get_vision_model_name()`** to look up the configured vision model key from Settings — not hardcoded `"minicpm_v2_6"`.
- **ValidationRunner runs 12 validators** (Sections: script, narration, subtitle, image, human, motion, audio, rendering, story, bgm, vision_review, cta).
- **`STOP_ON_QUALITY_GATE_FAILURE=true`** (default): critical quality gate failures raise `PipelineAbort`, skip downstream stages, and exit gracefully. Set to `false` to preserve old behavior (continue despite failures).
- **TTS cache key includes `emotion` and `sample_rate`** — identical text with different emotion/sample_rate produces different cache keys.
- **`PipelineAbort` exception** carries `stage` and `reason` fields; caught by `BuildPipeline` and `run_pipeline()` to produce concise abort summary.
- **TTS analytics disabled by default in tests** — `tts_analytics_enabled=False` in test settings to avoid side effects.

---

## Workspace Layout

```
workspace/jobs/<project-id>/
├── project.json
├── research/         research.md, research.json, sources.json
├── script/           script.md, script_original.md, script_pass1.md, script.json, enhancement-report.json
├── scenes/           scene-plan.json, scene-status.json
├── images/           scene-001.png … manifest.json, image-quality-summary.json, image-review-NNN.json, image-remediation-NNN.json
├── audio/            scene-001.mp3, .timing.json, .alignment.json
├── subtitles/        scene-001.srt, .ass
├── video/            scene-001.mp4 … final.mp4, final.work.mp4
├── review/           17+ review output files
├── remediation/      4 files
├── publish/          10 files (includes pinned-comment.txt)
├── bgm-debug/        5 files (written when BGM_VAD_ENABLED=true): speech_timeline.json, ducking_events.json, mix_profile.json, ffmpeg_filter.txt, audio_levels.csv
├── tts-debug/        per-scene TTS diagnostics (when TTS_DEBUG=true)
└── cache/tts/        Cartesia audio cache (content-addressed SHA256)
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

## 2026-07-22 — Fixes: single brand card, closing dedup, POLLINATIONS, Scene import, cartesia align
- `scene_planner.py`: `_mark_asset_scenes` now scans backward from the end and marks only the LAST closing scene as an asset scene — prevents missing the brand card when closing text spans >3 scenes and prevents duplicate brand cards.
- `scene_planner.py`: Before splitting, consecutive duplicate lines (caused by Pass 2 of the script enhancer re-appending closing/CTA phrases) are deduped.
- `docs/review/fix_vision_concurrency_tests.md`: Vision concurrency test fixes.
- `pollinations.py`, `huggingface.py`: Pillow resampling compatibility change (`Image.Resampling.LANCZOS` → `Image.LANCZOS`).
- `huggingface_vision_provider.py`: Vision cache key now incorporates prompt_text to avoid stale revocation.
- `build/pipeline.py`: Scene import path fixed from `ytfactory.retention.models` to `ytfactory.scenes.models`.
- `SharedSettings`: Cartesia settings aligned to `.env` (`speed=0.88`, `timeout=90`, `sample_rate=48000`, `emotion=contemplative`, `max_chars=2000`). **Note:** `.env.example` itself still lists the pre-alignment placeholder values (`speed=0.84`, `timeout=60`, `sample_rate=44100`, `emotion=calm`, `max_chars=2000`) — the Python `SharedSettings` class defaults above are the values actually in effect unless a real `.env` overrides them.
- `brand_config.yaml`: Opening disabled.

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
