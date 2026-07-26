# Spec: Motion Overlay Compositing Stage

## Integration constraints (read before implementing)
- Confirm the exact field name/location for scene mood/motion_type on the scene object before writing lookup code — do not assume, grep the actual `scene_planner` output schema first.
- This is an ADDITIVE change. Existing render behavior when `skip_overlays=true` (or unset) must be byte-for-byte unaffected — no changes to the current motion-effects filter chain logic.
- Confirm whether overlay compositing should be a second ffmpeg pass after existing motion rendering, or fused into the same `filter_complex` chain — do not assume; if unclear, ask before implementing, since this affects render time and correctness.
- Run the full existing test suite before and after implementation; report exact pass/fail counts and explain any new failures.
- Report per-scene render time delta introduced by overlay compositing.

## Overlay manifest

Curated set — 6 clips across 4 categories, vetted for pure-black background and clean loop suitability.

```json
{
  "smoke": [
    {
      "file": "Smoke/Soft rolling smoke.mp4",
      "blend_mode": "screen",
      "opacity": 0.25,
      "notes": "Full-frame rolling smoke/fog, fairly generic but clean bg"
    }
  ],
  "particles": [
    {
      "file": "Particles/Golden bokeh particles.mp4",
      "blend_mode": "screen",
      "opacity": 0.30,
      "notes": "Golden bokeh particles — primary choice for divine/sacred scenes"
    },
    {
      "file": "Particles/Warm ember - rising particles.mp4",
      "blend_mode": "screen",
      "opacity": 0.25,
      "notes": "Warm ember/rising particles — slow drift, good for penance/longing scenes"
    }
  ],
  "god_rays": [
    {
      "file": "God-rays/God-ray with visible dust in beam.mp4",
      "blend_mode": "screen",
      "opacity": 0.35,
      "notes": "God-ray with visible dust in beam — primary choice, richer than the vertical shaft variant"
    },
    {
      "file": "God-rays/Vertical god-ray - light shaft.mp4",
      "blend_mode": "screen",
      "opacity": 0.30,
      "notes": "Simpler single beam — backup/variant to avoid repetition across scenes"
    }
  ],
  "rain": [
    {
      "file": "Rain/Sparse falling light streaks.mp4",
      "blend_mode": "screen",
      "opacity": 0.20,
      "notes": "Subtle mist/rain — use only for mood-tagged scenes (grief, penance, longing)"
    }
  ],
  "grain": [
    {
      "file": "Grain/Film grain texture.mp4",
      "blend_mode": "grainmerge",
      "opacity": 0.07,
      "notes": "Mid-gray noise texture, 1920x1080 native — applied globally to every scene, not mood-conditional. Uses grainmerge blend, NOT screen (screen would wash out a mid-gray texture)."
    }
  ]
}
```

**Base path:** these are relative to the shared overlays assets root, now at `assets/overlays/` — Kilo can wire directly to this path per Implementation note 3, keeping the existing subfolder/filename structure (`assets/overlays/Particles/`, `assets/overlays/God-rays/`, etc.).

## Category → scene-mood mapping (for scene_planner / motion_type tagging)

| Category | When to use |
|---|---|
| `particles` (golden) | Divine/sacred moments, blessings, revelations |
| `particles` (ember) | Penance, longing, quiet devotion |
| `god_rays` | Scene reveals, emotional peaks, divine presence entering frame |
| `smoke` | Temple/ritual scenes, incense, sanctum interiors |
| `rain` | Only when `weather_mood` tag = grief/penance/longing (per earlier discussion — not a default, must be explicitly tagged, don't apply to sanctum/bright/serene scenes) |
| `grain` | Global, every scene, very low opacity (7%), `grainmerge` blend (not `screen`) — layered on top of any mood overlay, always applied regardless of scene mood |

## FFmpeg blend chain

Core single-overlay composite (screen blend, black-background overlay, opacity via alpha):

```bash
ffmpeg -i scene.mp4 -stream_loop -1 -i "overlays/Particles/Golden bokeh particles.mp4" \
  -filter_complex "\
    [1:v]scale=1920x1080,setsar=1,format=rgba,colorchannelmixer=aa=0.30,trim=duration=<scene_duration>[ov]; \
    [0:v][ov]blend=all_mode=screen:shortest=1[outv]" \
  -map "[outv]" -map 0:a? -c:a copy scene_composited.mp4
```

Key parameters:
- `-stream_loop -1` on the overlay input — loops it if scene is longer than the overlay clip
- `trim=duration=<scene_duration>` — cuts the looped overlay to exactly match scene length (pull from your existing per-scene duration value)
- `colorchannelmixer=aa=<opacity>` — controls overlay strength; use the `opacity` value from the manifest per overlay
- `scale=1920x1080` — normalize overlay to output resolution regardless of source res (your 2560x1440 sources downscale cleanly here)

For layering 2 overlays on one scene (e.g. god_rays + grain — this is the standard case now, since grain applies globally on top of any mood overlay) — chain a second blend stage on `[outv]` before final map:

```bash
ffmpeg -i scene.mp4 \
  -stream_loop -1 -i "overlays/God-rays/God-ray with visible dust in beam.mp4" \
  -stream_loop -1 -i "overlays/Grain/Film grain texture.mp4" \
  -filter_complex "\
    [1:v]scale=1920x1080,setsar=1,format=rgba,colorchannelmixer=aa=0.35,trim=duration=<scene_duration>[mood]; \
    [0:v][mood]blend=all_mode=screen:shortest=1[stage1]; \
    [2:v]scale=1920x1080,setsar=1,format=rgba,colorchannelmixer=aa=0.07,trim=duration=<scene_duration>[grain]; \
    [stage1][grain]blend=all_mode=grainmerge:shortest=1[outv]" \
  -map "[outv]" -map 0:a? -c:a copy scene_composited.mp4
```

If a scene has no mood-category match, skip stage1 and apply grain directly to the base scene.

## Implementation notes for Kilo

1. Add `overlay_manifest.json` (content above) to project config/assets directory
2. Extend `video_renderer` stage: after existing per-scene render (motion effects already implemented), add an overlay-compositing pass that:
   - Reads `motion_type`/mood tag already present on the scene object
   - Looks up matching category in the manifest (fallback: no overlay if no category match — don't force one)
   - Picks a specific clip within category (if >1, rotate/randomize across scenes to avoid repetition — e.g. alternate 70236/70241 for consecutive god_ray scenes)
   - Runs the blend filter chain above with that scene's duration
3. Overlay source clips already live in the project-independent shared assets path (`assets/overlays/<category>/<file>.mp4`) — reused across all videos, no per-project copies needed
4. Add a `skip_overlays` flag (env or per-run) for fast iteration/testing without the extra render pass
5. Log which overlay+opacity was applied per scene, for QA review
6. Filenames contain spaces (e.g. "Golden bokeh particles.mp4") — ensure all path handling in code properly quotes/escapes these (subprocess arg lists, not shell string concatenation) to avoid breakage

## Testing
- Render one scene per category through the chain, visually confirm no black-crush or harsh edges at chosen opacity
- Confirm loop point on shorter overlay clips (66070, 70025) isn't visually jarring when stretched to a long scene
- Confirm rendering time impact — blend adds an extra full-frame filter pass per scene, measure and report delta
