# Follow-up: Fix scene-plan persistence systemically (not per-path)

## Context from the sweep

The MOT_006 investigation found the in-memory-mutation-not-persisted bug in
two independent places:

1. `src/ytfactory/agents/nodes/video_renderer.py` (agentic LangGraph path) —
   **already patched** (lines 64-77), but as an ad-hoc, isolated write.
2. `src/ytfactory/video/pipeline.py:295-298` (`VideoPipeline.run()`, the
   sequential path) — **still broken**. This path is used by:
   - the `ytfactory render` CLI (`src/ytfactory/video/cli.py`)
   - `BuildPipeline._run_incremental()` and `BuildPipeline.run()`
   - remediation's `ProductionExecutor._regenerate_video_clip()` and
     `_full_regeneration()` (`src/ytfactory/review/remediation/executor.py:199,278`)

Any video going through path #2 will still trigger MOT_006, because
`quality_review_node` / `VideoQualityReviewEngine` reads `scene-plan.json`
from disk and sees pre-enrichment metadata.

Fixing #2 with another isolated write would just create a third instance of
the same bug pattern next time a new path touches this artifact. Do this
properly instead, in the order below. Do not skip ahead to later steps
before earlier ones are confirmed.

---

## Step 1 — Verify the existing fix end-to-end (do this first)

Before writing any new code:

1. Re-run `video_renderer_node` for `the-grass-that-refused-to-die-1` (or a
   fresh project if that one is awkward to re-run), through to
   `quality_review_node`.
2. Confirm the resulting `scenes/scene-plan.json` has real, non-empty
   `motion` values for all 40 scenes, with actual variety (not just two
   alternating values — check that assignments look reasonable per scene,
   not just "technically not static/none").
3. Confirm `MotionValidator._check_motion_variety` no longer fires MOT_006
   against this file.
4. Report the motion values for the first 10 scenes as evidence.

Stop and report back if this doesn't verify cleanly — don't proceed to
Step 2 until this is confirmed working.

---

## Step 2 — Build a shared scene-plan persistence helper

Introduce a single source-of-truth pair for reading/writing
`scenes/scene-plan.json`, e.g.:

```python
def load_scene_plan(project_id: str) -> list[dict]: ...
def save_scene_plan(project_id: str, scenes: list[dict], extra: dict = {}) -> None: ...
```

or a `ScenePlanRepository` wrapping the existing `ArtifactRepository` —
whichever fits the codebase's existing conventions better (check how
`ArtifactRepository` is used elsewhere before deciding).

Requirements:
- Centralizes the path/format logic currently duplicated across call sites.
- Makes the read/write contract explicit — any node that enriches scene
  metadata (motion, transitions, effects, visual_prompt, visual_metadata,
  linked_segment, etc.) must go through this helper to persist changes.
- Should not change the on-disk JSON format/schema — this is a refactor of
  *how* the file is read/written, not a data migration. Confirm existing
  consumers of `scene-plan.json` (anything not being touched in this change)
  still work against the same schema.

Do not implement this as a rewrite of unrelated logic — keep the change
scoped to persistence, not to what each node computes.

---

## Step 3 — Migrate all call sites to the shared helper

Migrate, in this order, confirming each one works before moving to the next:

1. `src/ytfactory/agents/nodes/video_renderer.py` — replace the ad-hoc write
   added in the original fix with a call to the shared helper.
2. `src/ytfactory/video/pipeline.py` (`VideoPipeline.run()`, ~line 295-298)
   — add the missing persistence via the shared helper. This is the actual
   fix for the still-broken sequential path.
3. `src/ytfactory/build/pipeline.py` (`BuildPipeline._run_pre_render_gate`,
   which already does an ad-hoc `linked_segment` write) — migrate to the
   shared helper for consistency, confirming its existing behavior is
   preserved.
4. Any other call site the shared-helper introduction surfaces — report
   anything found that wasn't already listed in the original sweep.

For each site: confirm existing tests still pass, and note anywhere
behavior changes (it shouldn't, other than fixing the actual bug).

---

## Step 4 — Verify the previously-broken paths are now fixed

1. Re-run (or run fresh) a project through `ytfactory render` CLI /
   `BuildPipeline`, and confirm `scene-plan.json` now has enriched motion
   data after `VideoPipeline.run()` completes — not just in memory.
2. Re-run `MotionValidator` against that output and confirm no MOT_006.
3. Specifically test the remediation path: trigger
   `ProductionExecutor._regenerate_video_clip()` and/or
   `_full_regeneration()` on a scene, and confirm the regenerated scene's
   motion metadata is correctly persisted and visible to a subsequent
   `quality_review` pass — this was flagged as "no scene-plan mutation via
   executor" in the sweep, so confirm whether remediation needs to call the
   shared helper directly or already gets correct data through the paths
   fixed in Step 3.

---

## Output format

```
## Step 1 — Existing fix verification
[pass/fail, evidence]

## Step 2 — Shared helper
[what was built, where, why that approach was chosen]

## Step 3 — Migration
[per call site: what changed, test status]

## Step 4 — Previously-broken paths verification
[pass/fail per path, evidence, including remediation-specific check]
```

Do not mark this complete until all four steps report pass with evidence —
not just "tests still pass," but actual motion data confirmed on disk for
at least one real project per path.
