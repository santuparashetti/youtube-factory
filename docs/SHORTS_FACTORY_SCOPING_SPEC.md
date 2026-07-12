# shorts_factory — Scoping Spec (v1)

**Status:** Draft scoping spec. Not yet an execution prompt.
**Purpose:** Second factory on the platform — proves out the
`video_core` boundary for real, and resolves several Bucket C
"ambiguous, defer until proven" items from the Phase 0/1 spec.

---

## 1. What it does

Takes a finished video's source materials (script + per-scene
images/audio) and produces 1-2 short-form vertical clips (9:16,
blur-fill background, fresh burned-in captions) from LLM-identified
hook-worthy scene ranges. Recomposes from source rather than cropping
the finished video — avoids mangling pre-existing burned-in captions.

## 2. The one architectural decision that shapes everything else

**shorts_factory does NOT read ytfactory's internal workspace schema.**
No `project.json`, no `scene-plan.json` parsing, no importing
ytfactory code. That would be a `Factory → Factory` dependency —
explicitly forbidden by every version of the platform spec, Phase 0
included.

**Revised approach (per-scene recomposition, not video cropping):**
Cropping the finished `final.mp4` turned out to be a dead end —
captions are burned into its pixels at 16:9 position, so any 9:16 crop
mangles them (confirmed by playback). Instead, shorts_factory
recomposes a fresh vertical video directly from source materials:

**Input contract — still generic files, just three kinds instead of
one:**
- script text (`.md`/`.txt` — the narration script)
- a per-scene manifest: `[{image_path, audio_path, narration_text,
  duration_seconds}, ...]` — a plain generic list, not ytfactory's
  internal `scene-plan.json` schema. ytfactory would need to *export*
  this shape (a thin, stable, generic manifest) rather than
  shorts_factory *importing* ytfactory's internal model — same
  principle as `chapters.txt` being a generic deliverable already.

This keeps the boundary intact: shorts_factory consumes a stable,
generic export contract, not ytfactory's actual internal artifacts or
code. Any factory with images+audio+narration-per-segment could feed
this, not just ytfactory.

## 3. Decision needed: promote `subtitles/` core engine to `video_core`?

Bucket C in the Phase 0/1 spec flagged `subtitles/` (excl. `editor/`) as
"plausibly generic but unproven — only one consumer exists today." That
condition is no longer true once shorts_factory needs to burn captions
into vertical clips.

**Recommendation:** do this as a small, separate, gated step —
same pattern as Phase 0/1, not bundled into shorts_factory's build:
1. Audit `ytfactory/subtitles/` (core engine, not `editor/` — the LLM
   editorial pass stays factory-specific, that part's still genuinely
   YouTube-brand-specific)
2. Confirm it's actually reusable as-is (timing/segmentation logic,
   not YT-scene-shaped)
3. Move it to `video_core.subtitles`, update ytfactory's imports (same
   zero-logic-change pattern as Phase 1)
4. Only then does shorts_factory import `video_core.subtitles` cleanly

**If you'd rather not gate shorts_factory on this** — shorts_factory
could instead do its own lightweight SRT-to-burned-caption step
independently for v1, and the promotion happens later once proven
useful twice. Your call — I'd lean toward doing the promotion first
since it's small, but it does add a step before shorts_factory itself
starts.

## 4. Pipeline stages (factory-owned, not video_core)

```
ingest → hook_analysis → clip_selection → scene_compose → export
```

- **ingest** — load script text + per-scene manifest, validate all
  referenced image/audio files exist
- **hook_analysis** — LLM (via `video_core.providers.llm`) reads the
  full narration text, identifies candidate contiguous scene-ranges
  that read as a strong standalone 1-2 min segment, with a hook-strength
  rationale. Factory-owned business logic — the *prompt* and *what makes
  a good hook* is product-specific judgment, same category as
  `branding/` in ytfactory.
- **clip_selection** — pick top 1-2 non-overlapping scene-ranges from
  hook_analysis candidates, target 60-120s total per short
- **scene_compose** — for each selected scene, recomposite its existing
  image + audio into a 9:16 frame (reused as-is, no new image/audio
  generation):
  - **background layer**: scale the source image (1280×720) to fill the
    full 1080×1920 frame, crop, gaussian blur — full-bleed backdrop,
    no lost content, no black bars
  - **foreground layer**: scale the same image to fit target width,
    centered over the blurred background
  - **optional pan/zoom**: subtle Ken Burns motion on the foreground
    over the scene's audio duration — **resolved 2026-07-13**:
    `video_core.cinematic.motion.MotionPlanner` and
    `video_core.cinematic.ffmpeg_filters.build_zoompan_filter` are now
    clean `video_core` imports (promoted from `ytfactory.cinematic`,
    also resolved AS-002 as a side effect). No shim needed:
    ```python
    from video_core.cinematic.motion import MotionPlanner
    from video_core.cinematic.ffmpeg_filters import build_zoompan_filter
    scene_dict = {"index": 1, "narration": narration_text, "duration_seconds": duration}
    spec = MotionPlanner().plan([scene_dict], profile="cinematic")[0]["motion"]
    vf = build_zoompan_filter(1080, 1920, fps, spec, duration)
    ```
  - **captions**: burn fresh, correctly positioned for the 9:16 frame,
    from the scene's `narration_text` — never cropped from a
    pre-existing burned-in caption, so no positioning/cutoff issue
  - concatenate composed scenes into one short
- **export** — write final short MP4(s) + manifest (source scene
  refs, hook rationale) to the workspace

**Note:** `vertical_reframe`/crop-from-finished-video approach and the
`subtitles/` promotion question (§3 in the prior draft) are no longer
relevant — this recompose-from-source approach sidesteps the burned-in
caption problem entirely by burning captions fresh, once, in the
correct position, rather than cropping an already-composited video.

## 5. CLI shape (mirrors ytfactory's pattern from the SDK docs' §4)

**Design rule: never infer file identity from filename.** Every input
is an explicit path, always — no assumptions about naming or co-location.

```bash
shorts_factory create <script.md> <scene-manifest.json>
shorts_factory analyze <job-id>       # hook_analysis, review candidates
shorts_factory select <job-id>        # clip_selection, or pass --auto
shorts_factory render <job-id>        # scene_compose + export
shorts_factory build <job-id>         # full pipeline in one shot
```

`scene-manifest.json` is the generic per-scene export mentioned in §2:
```json
[
  {"image_path": "...", "audio_path": "...", "narration_text": "...", "duration_seconds": 8.5},
  ...
]
```
ytfactory would need a small new export step to produce this from its
internal `scene-plan.json` + `timing.json` — a stable, generic shape,
not ytfactory's internal schema exposed directly.

Optional convenience for repeat use — a sidecar manifest so you don't
retype paths every time:
```bash
shorts_factory create --manifest source.yaml
```
v1: skip this, take the two CLI args directly. Add `--manifest` only if
retyping paths becomes genuinely annoying in practice.

## 6. Workspace layout (factory-owned, per the "never standardize
folder names" principle from the original blueprint)

```
workspace/shorts_jobs/<job-id>/
├── job.json              # source refs, status
├── source/                # copied/linked script.md + scene-manifest.json
├── analysis/              # hook candidates + rationale
├── clips/                 # selected scene-range definitions
├── render/                # per-clip composed vertical mp4 (pre-concat)
└── final/                 # short-1.mp4, short-2.mp4 + manifest.json
```

## 7. New settings (factory-specific, same pattern as ytfactory's)

```python
# in shorts_factory's own config, NOT ytfactory.config.Settings —
# separate factory, separate Settings(SharedSettings) subclass
shorts_target_count: int = 2          # soft cap, see §9 note
shorts_min_seconds: int = 60
shorts_max_seconds: int = 120
shorts_aspect_ratio: str = "9:16"
shorts_image_fit: str = "blur_fill"   # v2: "subject_aware_crop"
shorts_pan_zoom_enabled: bool = True  # subtle Ken Burns on foreground
```

## 8. Testing strategy — lighter than ytfactory, grows incrementally

Don't front-load a 12-validator quality gate like ytfactory's `review/`
— that took real iteration to justify. Start with:
- unit tests per stage (hook_analysis prompt parsing, clip_selection
  non-overlap logic, reframe dimensions correct)
- one integration test: real short video in → 2-3 clips out, correct
  aspect ratio, captions present
- add more validators only when a real failure mode shows up in
  practice, same as ytfactory presumably did

## 9. Explicit non-goals for v1

- Smart subject-aware image framing (blur-fill + centered foreground
  is the v1 default; a vision-model-driven "keep the subject
  off-center-composed nicely" framing is a real v2 improvement)
- New image/audio generation for shorts — v1 reuses existing per-scene
  assets only, per the decision already made
- Platform-specific formatting differences (TikTok vs Reels vs YT
  Shorts — treat as one 9:16 output for now)
- Auto-publishing shorts (export only, publish step is manual/future)
- More than 2 shorts per source video (revised down from "2-3" — see
  note below)
- A shared `factory_sdk` — still not built, still Appendix B; this
  factory duplicates whatever small CLI/bootstrap pattern it needs,
  same as ytfactory does today

**Note on count:** the original "2-3" target assumed cropping arbitrary
segments from a finished video. With recompose-from-source, each short
is built from real scene assets, so the practical ceiling is more about
how many genuinely strong standalone hooks the LLM finds in
`hook_analysis` — could be 1, could be 2, rarely meaningfully 3 for a
5-minute source video. Keep `shorts_target_count` as a soft cap, not a
promise.

---

## Open question before an execution prompt gets written

**ytfactory needs a new small export step** — a `scene-manifest.json`
generator (image/audio/narration/duration per scene, generic shape)
under `publish/` or similar. Small, additive, doesn't touch existing
outputs. Confirm this is fine to add, then I'll scope the execution
prompts for both this ytfactory addition and shorts_factory itself.

~~MotionPlanner/TransitionPlanner reuse check~~ — resolved 2026-07-13,
promoted to `video_core.cinematic`, clean import available, no shim
needed.
