# Task: VIDEO_SPLIT_LENGTH — Split final video into parts at scene boundaries

## Context

Post-processing utility that splits `final.mp4` into 2–3 parts at logical scene
boundaries. Output files go to Epidemic Sound for BGM/sound layering. Nothing in
the existing render pipeline changes — this is a pure addition after `final.mp4`
is produced.

---

## 1. Settings

**File:** `video_core/config/shared_settings.py`

Add two fields to `SharedSettings`:

```python
video_split_enabled: bool = Field(default=False, alias="VIDEO_SPLIT_ENABLED")
video_split_length_minutes: float = Field(default=4.0, alias="VIDEO_SPLIT_LENGTH")
```

**File:** `.env.example`

Follow the project convention — comment out the old line, add new value on the
next line. Add:

```
# VIDEO_SPLIT_ENABLED=false
VIDEO_SPLIT_ENABLED=false
# VIDEO_SPLIT_LENGTH=4.0
VIDEO_SPLIT_LENGTH=4.0
```

---

## 2. Split Logic — new file `ytfactory/video/splitter.py`

### Class

```python
class VideoSplitter:
    def split(
        self,
        input_path: Path,
        scenes: list[dict],       # from scene-plan.json; each has duration_seconds
        output_dir: Path,
        target_minutes: float,
        max_parts: int = 3,
    ) -> list[Path]:
        ...
```

### Algorithm

1. Build a list of `(scene_index, cumulative_seconds)` from `scenes[].duration_seconds`.

2. Compute `target_seconds = target_minutes * 60`.
   Define the **split window** as `[target_seconds * 0.75, target_seconds * 1.15]`.

3. Walk forward through cumulative scene timestamps. When the cumulative time
   first enters the window, mark the **current scene boundary** as the split
   point. Record that timestamp. Reset accumulator and continue for the next part.

4. Hard cap: maximum `max_parts - 1` split points → never more than `max_parts`
   output files. Stop looking for more splits once the cap is reached.

5. **Micro-tail absorption:** if the remaining tail after the last split is
   less than 60 seconds, absorb it into the previous part rather than creating
   a near-empty final segment.

6. **Window miss fallback:** if no scene boundary falls within the window (e.g.
   a single very long scene spans the entire window), fall back to the hard
   `target_seconds` timestamp as the cut point.

7. **No-split guard:** if the total video duration is less than
   `target_seconds * 0.75`, log a warning and return an empty list — do not
   produce a single `final_part1.mp4` that is just a copy of `final.mp4`.

8. Return the list of output `Path` objects written.

### FFmpeg execution (per segment)

Use stream copy — no re-encode:

```
ffmpeg -ss {start_seconds} -i {input_path} -t {segment_duration_seconds} \
       -c copy -avoid_negative_ts make_zero {output_path}
```

Output filenames: `final_part1.mp4`, `final_part2.mp4`, `final_part3.mp4` — written
to the same `video/` directory as `final.mp4`.

### split_manifest.json

After all segments are written, write `video/split_manifest.json`:

```json
{
  "parts": [
    {
      "part": 1,
      "path": "final_part1.mp4",
      "start_seconds": 0,
      "end_seconds": 243.5,
      "scene_count": 6
    },
    {
      "part": 2,
      "path": "final_part2.mp4",
      "start_seconds": 243.5,
      "end_seconds": 487.0,
      "scene_count": 7
    }
  ]
}
```

---

## 3. Wiring

Find the exact line in `build/pipeline.py` (or `two_phase/pipeline.py`) that
produces the completed `final.mp4`. Immediately after that step succeeds, add:

```python
if settings.video_split_enabled:
    from ytfactory.video.splitter import VideoSplitter
    scene_plan_path = workspace / "jobs" / project_id / "scenes" / "scene-plan.json"
    scenes = json.loads(scene_plan_path.read_text())["scenes"]
    parts = VideoSplitter().split(
        input_path=final_mp4_path,
        scenes=scenes,
        output_dir=final_mp4_path.parent,
        target_minutes=settings.video_split_length_minutes,
    )
    if parts:
        logger.info(f"Video split into {len(parts)} parts: {[str(p) for p in parts]}")
```

Do not add a new pipeline stage. Do not update `pipeline-status.json`. Do not
trigger any review validators. This is a post-processing utility only.

---

## 4. Tests — `tests/test_video_splitter.py`

Mock all FFmpeg subprocess calls. Test the cut-point arithmetic independently of
FFmpeg execution.

| Test case | Expected behaviour |
|---|---|
| 8-min video, 14 scenes, 4-min target | 2 parts; split at nearest scene boundary in `[180s, 276s]` window |
| 6-min video, 10 scenes, 4-min target | 2 parts; 2-min tail is acceptable (above 60s threshold) |
| 4-min video, 8 scenes, 4-min target | No split; total < `target * 0.75` (180s); warning logged; empty list returned |
| Micro-tail absorption | Split would leave 45s tail → absorbed into previous part |
| Max-parts cap | 13-min video, 4-min target → 3 parts max, not 4; cap enforced |
| Window miss fallback | Single 9-min scene spans entire window → hard `target_seconds` timestamp used |
| FFmpeg command correctness | Assert `-ss`, `-t`, `-c copy`, `-avoid_negative_ts make_zero` flags present |
| `split_manifest.json` | Written with correct `part`, `path`, `start_seconds`, `end_seconds`, `scene_count` fields |
| `video_split_enabled=False` | `VideoSplitter` never instantiated; no files written |
| No-split guard log | Warning logged when total duration below threshold |

---

## 5. Invariants

- **Never modify `final.mp4`** — stream copy only; input is always read-only.
- **`video_split_enabled=False` by default** — existing behaviour unchanged unless
  opted in via `.env`.
- **`scene-plan.json` is the source of truth for scene durations** — do not
  re-derive durations from audio files or the video file itself.
- **No re-encode** — `-c copy` always. These files go to Epidemic Sound for audio
  replacement; video must be lossless-copy.
- **`SharedSettings`** is the correct home for these two settings — they are
  cross-pipeline (same layering-rule reasoning as prior shared settings).
- **Not a pipeline stage** — does not update `pipeline-status.json`, does not
  trigger review validators, does not appear in the stage-progress tracker.
- **Max 3 parts** — hard-coded default for `max_parts`; do not make this
  configurable unless a future need arises.

---

## 6. Do NOT touch

- Existing render pipeline (`video/pipeline.py`, `video/ffmpeg.py`)
- `scene-plan.json` schema — read only, never written by this task
- Any review validator or remediation hook
- Brand card logic
- `pipeline-status.json` writer
