# Verification & Regression Sweep: video_renderer_node state-persistence fix

## Context

`video_renderer_node` was found to mutate the scene list in memory (adding
`MotionPlanner` / `TransitionPlanner` / `EffectsPlanner` output) without
persisting it back to `scenes/scene-plan.json`. Downstream nodes that read
`scene-plan.json` from disk — including `quality_review_node` /
`VideoQualityReviewEngine` — saw the original, unenriched scene data, which
caused every scene to default to `motion: static/none` and triggered
`MOT_006` (40 consecutive scenes with no motion variety).

Fix applied: `video_renderer_node` now writes the enriched scene plan back to
`scenes/scene-plan.json` and returns the enriched `scene_plan` into LangGraph
state. File changed: `src/ytfactory/agents/nodes/video_renderer.py`.

This prompt has two goals:
1. Confirm the fix actually resolves the original failure end-to-end (not
   just that unit tests pass).
2. Check whether the same bug pattern — in-memory mutation that is never
   persisted to the file downstream nodes read from — exists anywhere else
   in the LangGraph pipeline.

Do not silently patch anything found. Report first, propose fixes second,
and wait for confirmation before changing code outside of `video_renderer.py`
unless explicitly told to proceed.

---

## Part 1 — Confirm the original fix end-to-end

1. Identify (or re-run) the specific job/video that originally produced the
   MOT_006 violation on scenes 1–40.
2. Re-run the pipeline from `scene_planner` (or from `video_renderer_node`
   if scene planning doesn't need to be redone) through `quality_review_node`
   for that job.
3. Inspect the resulting `scenes/scene-plan.json` on disk and confirm:
   - Each scene has a non-null `motion` value.
   - The motion values show actual variety (e.g., a mix of `push_in`,
     `drift`, etc.), not just "not static/none" — a validator that only
     checks for absence of repeats could still pass on a low-quality
     assignment (e.g., alternating only two values, or assigning motion
     that doesn't match scene content/duration).
4. Re-run `MotionValidator` (`_check_motion_variety`) directly against that
   scene-plan.json and confirm MOT_006 no longer fires.
5. Confirm the state returned into LangGraph and the file written to disk
   agree with each other (no drift between the two) at the point
   `quality_review_node` reads them.
6. Report: pass/fail for each of the above, with the actual motion values
   assigned for a sample of scenes (e.g., first 10) as evidence.

---

## Part 2 — Sweep for the same pattern elsewhere in the graph

The pipeline flow is:

```
START → research_agent/script_enhancer → script_writer → human_review_script
→ scene_planner → human_review_scenes → generate_scene_assets (per-scene, parallel)
→ video_renderer → video_concatenator → cta → quality_review → remediation
→ publish → END
```

For every node in this graph, check:

1. Does this node read `scene-plan.json` (or any other shared artifact —
   e.g. subtitle files, CTA overlay config, BGM mix metadata) from disk,
   from LangGraph state, or both?
2. Does this node mutate that data in memory (add/modify fields) as part
   of its own processing?
3. If it mutates in memory, does it persist those changes back to the same
   file/location that other nodes read from — or could a downstream node
   silently see stale data, the same way `quality_review_node` did before
   the fix?

Pay particular attention to:
- `generate_scene_assets` (runs per-scene in parallel — a good candidate
  for the same in-memory-only mutation, and parallelism adds risk of race
  conditions on top of it)
- `video_concatenator` and `cta` (both likely read/modify scene or video
  metadata downstream of `video_renderer`)
- `remediation` (if it re-processes scenes flagged by `quality_review`,
  confirm it's reading the *current* enriched state, not a stale copy)
- Any node that reads `scenes/scene-plan.json` more than once across the
  graph run — each read should reflect the latest writes, not a cached
  version loaded at graph start.

For each node, report:
- Node name
- Whether it reads/writes shared scene or pipeline metadata
- Whether an in-memory-mutation-not-persisted risk exists
- If found, whether it's an active bug (something already silently wrong,
  like MOT_006 was) or a latent risk (currently harmless but fragile)

---

## Part 3 — Recommend a structural fix (optional, report only — don't implement yet)

If more than one node has this same risk, is there a shared helper /
single source-of-truth pattern (e.g., a `load_scene_plan()` /
`save_scene_plan()` pair, or a single state-sync point at the end of every
node) that could prevent this entire class of bug going forward, rather
than patching each node individually? Propose it at a high level — file(s)
affected, rough approach — without writing the implementation yet.

---

## Output format

```
## Part 1 — Fix Verification
[pass/fail per check, with evidence]

## Part 2 — Pipeline Sweep
[table or list: node | reads/writes shared state | risk found (yes/no) | active bug or latent risk]

## Part 3 — Structural Recommendation
[proposal, not implemented]
```
