# Claude Code Prompt — Sync Docs After cinematic/ Promotion (4742590, 925f4f7, a0bd568)

Paste into Claude Code, run from repo root. Targeted edits only.

---

## File 1: `docs/context/MASTER_CONTEXT.md`

### Edit A — Changelog
Add above the Phase 1 entry:
```
## 2026-07-13 — cinematic/ promoted to video_core (commits 4742590, 925f4f7, a0bd568)
Moved motion.py, transitions.py, profiles.py, effects.py, config.py from
ytfactory/cinematic/ to video_core/cinematic/ — zero prior Settings/
workspace coupling, pure relocation. Extracted FFmpegRenderer._vf_spatial
and _t_factor into standalone video_core.cinematic.ffmpeg_filters.
build_zoompan_filter() — zero behavior change, FFmpegRenderer now
delegates to it. Resolves AS-002 (agentic/sequential renderer
duplication) — both paths now import from one canonical location.
Test count unchanged: 2165 passing, 0 failing.
```

### Edit B — Source layout section
Add `cinematic/` under the `video_core/` tree:
```
├── video_core/
│   ├── providers/
│   ├── models/
│   ├── domain/
│   ├── config/
│   └── cinematic/        # NEW — MotionPlanner, TransitionPlanner,
│                          # profiles, effects, ffmpeg_filters
```

### Edit C — Key Invariants
Add a line noting `MotionPlanner`/`TransitionPlanner` now live in
`video_core.cinematic` and are usable by any factory without a shim.

### Do NOT touch
Provider tables, LAMM section, workspace layout, review/bgm/publish
internals — none of that changed.

---

## File 2: `ARCHITECTURE_AUDIT_2026_07_12.md` (or wherever AS-002 lives)

Move AS-002 from "Still Open" to "Resolved," with:
```
AS-002 — Agentic/sequential renderer duplication — RESOLVED 2026-07-13
(commits 4742590, 925f4f7, a0bd568). Both video/pipeline.py and
agents/nodes/video_renderer.py now import MotionPlanner/TransitionPlanner
from video_core.cinematic — single canonical location, no divergent
instantiation.
```

---

## File 3: `CLAUDE.md`

If `cinematic/` or `MotionPlanner`/`TransitionPlanner` is mentioned
anywhere (check the Architecture section), update the path reference to
`video_core.cinematic`. If not currently mentioned, no change needed —
don't add a new section for something that wasn't documented before.

---

## Verification

```bash
grep -rn "ytfactory\.cinematic\|ytfactory/cinematic" docs/ CLAUDE.md
```
Any hits are stale path references — fix them.

Commit: `docs: sync MASTER_CONTEXT, audit doc, and CLAUDE.md with cinematic/ promotion`
