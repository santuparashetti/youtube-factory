# MotionPlanner / TransitionPlanner Reusability Diagnostic
**Date:** 2026-07-13  
**Context:** AS-002 (audit flag — duplication between `VideoPipeline` and `video_renderer_node`).  
**Trigger:** shorts_factory needs Ken Burns pan/zoom on a single static image; check before writing fresh math.

---

## What each class actually does

### `MotionPlanner` (`src/video_core/cinematic/motion.py`)
Pure data transformation — no I/O, no LLMs, no dimensions.

1. Classifies dominant emotion per scene via `classify_scene(narration, position)` (already in `video_core`).
2. Maps emotion → `(motion_type, scale_tier)` via a profile config table (`cinematic/profiles.py`).
3. Resolves to normalized geometry: `(start_scale, end_scale, anchor_x, anchor_y, drift_x, drift_y)` — all values as fractions of the frame, completely aspect-ratio agnostic.
4. Writes a `MotionSpec` dict into `scene["motion"]`.

No `width`/`height` anywhere in this class.

### `FFmpegRenderer._vf_spatial()` (`src/ytfactory/video/ffmpeg.py:35–88`)
Where the actual zoompan filter string is built.

- Takes `width`, `height`, `fps`, `motion: dict`, `duration_hint` as **explicit parameters** — not from Settings.
- Computes the full zoompan or scale+crop FFmpeg expression from those inputs.
- Pure math: ~45 lines, no I/O, no Settings access inside the method body.
- **Only YT coupling:** it's a method on `FFmpegRenderer`, whose `__init__` does `self.settings = Settings()`. The method itself has zero Settings use.

### `TransitionPlanner` (`src/video_core/cinematic/transitions.py`)
Purely about boundaries between consecutive scenes — emotion-pair matrix → fade type/duration. **Not relevant to shorts_factory** (single-image use case has no inter-scene transitions).

---

## Bucket classification

**Reusable with extraction — small extraction.**

| Component | Usable as-is? | Note |
|---|---|---|
| `MotionPlanner.plan([single_scene], profile=...)` | Yes | Works on a 1-element list; `scene_position` defaults to 0.5 |
| `_resolve_motion()` / `_asset_motion()` | Yes | Pure math, no dependencies |
| `ProfileConfig` / `get_profile_config()` | Yes | Pure data, no Settings |
| `FFmpegRenderer._vf_spatial(w, h, fps, motion, dur)` | **One lift needed** | Method body is clean; trapped inside a class that has `Settings()` in `__init__` |

The one change needed: extract `_vf_spatial()` and `_t_factor()` from `FFmpegRenderer` into a standalone function — `build_zoompan_filter(width, height, fps, motion, duration_hint)`. That's ~45 lines, pure math, no ytfactory imports.

After that, shorts_factory can call:

```python
scene_dict = {"index": 1, "narration": narration, "duration_seconds": duration}
spec = MotionPlanner().plan([scene_dict], profile="cinematic")[0]["motion"]
vf = build_zoompan_filter(1080, 1920, 30, spec, duration)
```

No other code changes. `FFmpegRenderer` can call the same standalone function internally — zero behavior change to the existing pipeline.

---

## AS-002 / `video_core` candidacy

**This diagnostic is evidence in favor of promoting MotionPlanner/TransitionPlanner to `video_core` now.**

Current coupling audit of the cinematic package:

| File | Settings import? | Workspace paths? | ytfactory domain types? | External imports |
|---|---|---|---|---|
| `cinematic/motion.py` | No | No | No | `video_core.providers.tts.emotion` only |
| `cinematic/transitions.py` | No | No | No | `video_core.providers.tts.emotion` only |
| `cinematic/profiles.py` | No | No | No | stdlib only |
| `cinematic/effects.py` | No | No | No | stdlib only |

All four are written like `video_core` modules already. Their only external dependency is `classify_scene` which is already in `video_core`. Moving them resolves AS-002 by creating one canonical import location for both `VideoPipeline` (sequential) and `video_renderer_node` (agentic).

### Promotion scope (if actioned)

1. Move `cinematic/{motion,transitions,profiles,effects}.py` → `src/video_core/cinematic/`
2. Lift `_vf_spatial()` + `_t_factor()` from `FFmpegRenderer` → `src/video_core/cinematic/ffmpeg_filters.py` as standalone functions
3. Update imports in `video/pipeline.py`, `agents/nodes/video_renderer.py`, `video/ffmpeg.py`
4. `FFmpegRenderer` stays in `ytfactory/video/` as a thin orchestration class (it reads `Settings` and is inherently pipeline-specific)

**Estimated scope:** 8–10 files touched, no behavior changes, resolves AS-002 and unblocks shorts_factory pan/zoom in a single pass.

---

## Recommendation

Do the promotion as a Phase 2 step (alongside `ytfactory.shared.constants` extraction). The extraction of `_vf_spatial` into a standalone function is a prerequisite and takes ~15 minutes; the full `cinematic/` move is the real work but bounded and mechanical.

For shorts_factory specifically: if the promotion is not yet scheduled, a thin shim that instantiates `MotionPlanner` and calls `FFmpegRenderer._vf_spatial` directly (passing `1080, 1920`) is a valid stop-gap — but document it as a Bucket-C exception pending the Phase 2 promotion.
