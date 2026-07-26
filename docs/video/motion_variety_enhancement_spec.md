# Motion Variety Enhancement — Spec
## MotionPlanner Cooldown / Rebalancing Pass

---

# Background

The MOT_006 investigation (persistence bug + emotion-classifier tuning) fixed
the original 40-scene `static/none` violation. With the classifier fix
applied, the `the-grass-that-refused-to-die-1` project now produces a varied
emotion distribution (curiosity, hope, awe, compassion, mystery, reflection,
urgency, peace) instead of being dominated by `revelation`.

However, `MotionValidator._check_motion_variety` still reported residual
violations on that and other projects: runs of 3–6 consecutive identical
non-static motions (`push_in`, `pull_out`). This is **not** a classifier bug.
The emotion classifier was producing accurate content-driven labels. The issue
is downstream: the `balanced` motion profile maps each emotion to a single
motion type, so any run of consecutive scenes sharing the same emotion —
normal and expected in narration with sustained emotional beats — produces a
run of identical motion which the validator then flags.

**Resolution:** Implemented Approach B (post-planning rebalancing pass).
Chasing this by distorting the emotion classifier would reintroduce the
original problem. The fix lives in the motion-assignment layer.

---

# Implementation

## Approach chosen

**Approach B** — post-planning rebalancing pass.

**Reasoning:** testability and isolation. A separate pass can be verified
against already-produced `scene-plan.json` files (including the 5 regression
projects) without risk to the core `MotionPlanner`. If insufficient, Approach A
(cooldown) can be layered on top later.

## Acceptable-motion sets defined

Added to `src/video_core/cinematic/profiles.py`:

```
curiosity:     [push_in, drift]
wonder:        [pull_out, drift]
reflection:    [drift, static]
mystery:       [push_in, drift]
peace:         [static, drift]
hope:          [pull_out, push_in]
compassion:    [push_in, drift]
urgency:       [push_in, drift]
sadness:       [pull_out, drift]
awe:           [pull_out, drift]
determination: [push_in, drift]
revelation:    [static, drift]
```

Each set preserves the existing default as the first choice, with one
emotion-compatible alternative ranked below it. Nothing arbitrary — each
alternative fits the emotional register.

## What was built

**New module:** `src/video_core/cinematic/rebalancer.py`

- `RebalanceConfig` dataclass with `max_run_length` (default 2) and
  `rebalance_stride` (default 2).
- `MotionRebalancer.rebalance(scenes)` — walks the scene list, detects runs
  exceeding `max_run_length`, and substitutes every `rebalance_stride`-th
  scene in the over-length run with the least-recently-used alternative motion
  from the same emotion's acceptable set.

**Integrated into two orchestration points:**

1. `src/ytfactory/agents/nodes/video_renderer.py` — called after
   `_motion_planner.plan()`, `_transition_planner.plan()`,
   `_effects_planner.plan()`, before SceneRepository write and per-scene
   rendering.
2. `src/ytfactory/video/pipeline.py` (`VideoPipeline.run()`) — same position
   in the sequence.

**Persistence:** All rebalanced motion assignments flow through
`SceneRepository().save_scenes()`, consistent with the MOT_006 persistence
fix. No ad-hoc writes.

## Regression results

| Project | Scenes | Violations before | Violations after |
|---|---|---|---|
| `the-grass-that-refused-to-die-1` | 40 | 5 | **0** |
| `a-walk-through-the-valley` | 19 | 1 | **0** |
| `what-plato-knew-about-happiness` | 31 | 1 | **0** |
| `the-mind-that-never-says-enough` | 60 | 6 | **0** |
| `you-were-so-busy-building-a-life-you-forgot-to-live` | 36 | 1 | **0** |

Configuration: `max_run_length=2`, `rebalance_stride=2`.

Emotion distributions unchanged from the corrected-diff run; only motion types
substituted within each emotion's acceptable set.

## Confirmation

- Persistence via `SceneRepository` confirmed for both orchestration points.
- `MotionValidator._check_motion_variety` threshold unchanged (validator
  still flags at 3+ consecutive identical motion).
- Short-run projects (under 3 consecutive identical motions) are unaffected —
  the rebalancer only modifies scenes that would otherwise violate.
- Full test suite: **2600 passed**, 2 pre-existing vision-concurrency failures
  unrelated to this change, 1 skipped.
