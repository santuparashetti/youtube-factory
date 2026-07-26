# Task 2.11 — Overlay Fixes: Visual Keyword Trigger + Grain Brightness + Opacity
**File:** `src/ytfactory/video/overlay.py` + `src/ytfactory/video/pipeline.py`
**Read first:** both files in full before touching anything
**Baseline:** current test count — do not regress

---

## Token Efficiency

- No new LLM calls
- No new models or settings beyond what's listed
- Code changes only

---

## Fix 1 — Visual Prompt Keyword Trigger for Rain, Fog, Particles, Smoke ONLY

**Problem:** Rain overlay only triggers on mood tags (grief/penance/longing).
Scene 25 has a downpour visual prompt but mood=hopeful — no rain overlay fires.
Same issue applies to particles, smoke, fog/mist scenes.

**Scope:** Visual keyword check applies ONLY to these four:
`rain`, `particles`, `smoke`, `fog`. God rays and all other overlays
continue to use mood/motion_type only — no keyword check for them.

**Fix:** In `select_category()`, after existing motion_type/mood logic,
add secondary visual prompt keyword check for four categories only:

```python
# Visual keyword check — ONLY rain, particles, smoke, fog
_VISUAL_KEYWORDS: dict[str, set[str]] = {
    "rain": {
        "rain", "downpour", "monsoon", "rainfall", "rainstorm",
        "drizzle", "shower", "precipitation", "pouring",
    },
    "particles": {
        "particles", "dust motes", "floating dust", "pollen",
        "embers", "sparks", "fireflies", "motes", "spores",
        "drifting particles", "swirling dust",
    },
    "smoke": {
        "smoke", "incense", "steam", "smoke rising", "smoky",
        "vapour", "vapor",
    },
    "fog": {
        "mist", "fog", "haze", "misty", "foggy", "low cloud",
        "morning mist", "evening mist",
    },
}

def _category_from_visual_prompt(self, visual_prompt: str) -> str | None:
    """
    Secondary visual keyword check — ONLY for rain/particles/smoke/fog.
    Returns None if no match.
    Priority: particles > smoke > fog > rain
    """
    prompt_lower = visual_prompt.lower()
    for category in ["particles", "smoke", "fog", "rain"]:
        keywords = _VISUAL_KEYWORDS.get(category, set())
        if any(kw in prompt_lower for kw in keywords):
            return category
    return None

def select_category(self, scene: dict) -> str | None:
    # existing motion_type / mood logic — keep exactly as-is
    # existing_result = current logic...

    # Primary always wins
    if existing_result:
        return existing_result

    # Secondary: visual keyword check for rain/particles/smoke/fog only
    visual_prompt = scene.get("visual_prompt", "")
    return self._category_from_visual_prompt(visual_prompt)
```

---

## Fix 2 — All Overlays Must Not Darken or Overpower the Video

**Problem:** Overlays — both grain and mood overlays (rain, particles,
smoke, fog, god_rays) — are too visible and making the video darker.
Overlays must enhance atmosphere subtly, never overpower the original
video or reduce its brightness.

**Fix: Reduce all overlay opacities significantly.**

Update the manifest/config where overlay opacities are defined:

```python
# Maximum permitted opacities — none should exceed these
OVERLAY_MAX_OPACITIES = {
    "grain":     0.03,   # was 0.07 — barely visible texture only
    "rain":      0.12,   # was 0.20-0.35 — light atmospheric suggestion
    "particles": 0.10,   # was 0.20-0.35 — barely visible floating elements
    "smoke":     0.10,   # was 0.20-0.35 — very light haze only
    "fog":       0.10,   # same as smoke
    "god_rays":  0.12,   # was 0.20-0.35 — subtle light enhancement only
}
```

If opacities are defined in the overlay manifest JSON
(`assets/overlays/manifest.json` or similar), update the values there.
If they are hardcoded in `overlay.py`, update the constants there.
Find the actual location and update all values to not exceed the maximums
above.

**Fix: Grain blend mode — switch to `overlay` from `grainmerge`.**

`grainmerge` (addition minus 128) actively darkens mid-tones.
`overlay` blend mode preserves luminosity while adding texture:

```python
# In FFmpeg grain filter chain:
# Change blend mode from grainmerge → overlay
# This preserves scene brightness
grain_filter = (
    f"[grain_scaled]blend=all_mode=overlay:all_opacity={GRAIN_OPACITY}"
)
```

Adapt to match the real FFmpeg filter construction in the codebase —
the principle is: overlay blend mode, not grainmerge.

**Fix: Add screen blend mode check for all mood overlays.**

Mood overlays (rain, particles, smoke, fog, god_rays) must use `screen`
blend mode, not `overlay` or `normal`. Screen mode only adds light —
it can never make the image darker than the original:

```
screen blend: result = 1 - (1 - base) * (1 - overlay)
```

This guarantees no darkening regardless of overlay content.

Verify existing mood overlay blend mode is `screen`. If it's anything
else, change it to `screen`.

---

## Fix 3 — Grain Threshold: 40% Majority Rule

**Problem:** Grain fires if ANY scene matches era/mood/style criteria.
Almost every Atma Theory video triggers grain because one scene is historical.

**Fix:** Change from "any scene matches" to "40% of scenes must match":

```python
def _should_apply_grain(self, scenes: list[dict]) -> bool:
    content_scenes = [
        s for s in scenes
        if s.get("scene_type") != "brand_card"
    ]
    if not content_scenes:
        return False

    matching = 0
    for s in content_scenes:
        vm = s.get("visual_metadata", {})
        # handle both dict and VisualMetadata object (Task 2.9 pattern)
        era = (vm.get("era", "") if isinstance(vm, dict)
               else getattr(vm, "era", "")).upper()
        mood = (vm.get("mood", "") if isinstance(vm, dict)
                else getattr(vm, "mood", "")).lower()
        style = (vm.get("visual_style", "") if isinstance(vm, dict)
                 else getattr(vm, "visual_style", "")).upper()

        if era in _GRAIN_ERAS or mood in _GRAIN_MOODS or style in _GRAIN_STYLES:
            matching += 1

    threshold = 0.40
    result = (matching / len(content_scenes)) >= threshold
    logger.debug(
        f"Grain check: {matching}/{len(content_scenes)} scenes "
        f"({matching/len(content_scenes):.0%}) — "
        f"threshold={threshold:.0%} — {'ON' if result else 'OFF'}"
    )
    return result
```

---

## Tests

```python
# Fix 1 — visual keyword trigger (rain/particles/smoke/fog only)
def test_rain_triggered_by_visual_keyword():
    scene = {
        "motion_type": "static",
        "visual_metadata": {"mood": "hopeful"},
        "visual_prompt": "a sunflower standing in a downpour",
    }
    assert compositor.select_category(scene) == "rain"

def test_particles_triggered_by_visual_keyword():
    scene = {
        "motion_type": "static",
        "visual_metadata": {"mood": "peaceful"},
        "visual_prompt": "dust motes floating in shaft of morning light",
    }
    assert compositor.select_category(scene) == "particles"

def test_smoke_triggered_by_visual_keyword():
    scene = {
        "motion_type": "static",
        "visual_metadata": {"mood": "reflective"},
        "visual_prompt": "incense smoke rising slowly in a quiet room",
    }
    assert compositor.select_category(scene) == "smoke"

def test_fog_triggered_by_visual_keyword():
    scene = {
        "motion_type": "static",
        "visual_metadata": {"mood": "mysterious"},
        "visual_prompt": "a misty valley at dawn",
    }
    assert compositor.select_category(scene) == "fog"

def test_god_rays_NOT_triggered_by_visual_keyword():
    # god_rays uses mood/motion_type only — no keyword check
    scene = {
        "motion_type": "static",
        "visual_metadata": {"mood": "hopeful"},
        "visual_prompt": "shafts of light filtering through columns",
    }
    # keyword check doesn't cover god_rays — should return None
    # unless motion_type or mood already matched
    result = compositor._category_from_visual_prompt(
        scene["visual_prompt"]
    )
    assert result is None

def test_primary_logic_takes_priority_over_keyword():
    scene = {
        "motion_type": "particles",  # primary match
        "visual_metadata": {"mood": "hopeful"},
        "visual_prompt": "heavy rain falling",  # keyword would say rain
    }
    result = compositor.select_category(scene)
    assert result == "particles"  # primary wins

def test_no_keyword_returns_none():
    scene = {
        "motion_type": "static",
        "visual_metadata": {"mood": "hopeful"},
        "visual_prompt": "a sunflower in golden hour light",
    }
    assert compositor.select_category(scene) is None

# Fix 2 — opacity and brightness
def test_grain_opacity_does_not_exceed_max():
    assert GRAIN_OPACITY <= 0.03

def test_grain_blend_mode_is_overlay_not_grainmerge():
    filter_str = build_grain_filter(width=1280, height=720)
    assert "grainmerge" not in filter_str.lower()
    assert "overlay" in filter_str.lower()

def test_mood_overlay_uses_screen_blend():
    # screen mode never darkens — verify all mood overlays use it
    for category in ["rain", "particles", "smoke", "fog", "god_rays"]:
        filter_str = build_overlay_filter(category, width=1280, height=720)
        assert "screen" in filter_str.lower(), \
            f"{category} overlay must use screen blend"

def test_all_overlay_opacities_within_max():
    for category, max_opacity in OVERLAY_MAX_OPACITIES.items():
        actual = get_overlay_opacity(category)
        assert actual <= max_opacity, \
            f"{category} opacity {actual} exceeds max {max_opacity}"

# Fix 3 — grain threshold
def test_grain_fires_at_40_percent():
    historical = [{"scene_type": "content",
                   "visual_metadata": {"era": "HISTORICAL",
                                       "mood": "reverent",
                                       "visual_style": "CINEMATIC"}}] * 12
    modern = [{"scene_type": "content",
               "visual_metadata": {"era": "MODERN",
                                   "mood": "hopeful",
                                   "visual_style": "REALISTIC"}}] * 17
    assert compositor._should_apply_grain(historical + modern) is True

def test_grain_skipped_below_40_percent():
    historical = [{"scene_type": "content",
                   "visual_metadata": {"era": "HISTORICAL",
                                       "mood": "reverent",
                                       "visual_style": "CINEMATIC"}}] * 5
    modern = [{"scene_type": "content",
               "visual_metadata": {"era": "MODERN",
                                   "mood": "hopeful",
                                   "visual_style": "REALISTIC"}}] * 24
    assert compositor._should_apply_grain(historical + modern) is False
```

---

## Do NOT change

- God rays and other overlay mood/motion_type selection — working correctly
- Time-gate approach for mood overlays on continuous video
- Audio pipeline
- `OVERLAY_GRAIN_ENABLED` hard override setting
- Any validator, scene planner, or prompt template
- Test baseline — do not regress
