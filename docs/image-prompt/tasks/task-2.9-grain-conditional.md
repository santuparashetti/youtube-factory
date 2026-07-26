# Task 2.9 — Grain Overlay: Conditional, Not Mandatory
**File:** `src/ytfactory/video/overlay.py` + `src/ytfactory/video/pipeline.py`
**Scope:** Grain overlay behaviour only — do not touch mood overlay logic
**Baseline:** current test count after Task 2.8 — do not regress

---

## Token Efficiency

- No new LLM calls
- No new models or settings beyond what's listed below
- Code change only

---

## Current Behaviour (wrong)

Grain is applied unconditionally to every video, whole-duration, at the
end of the overlay pass. There is no way to disable it per-scene or
per-video without setting `skip_overlays=true` globally (which also
disables mood overlays).

---

## Required Behaviour

Grain must be conditional — applied only when the overall scene
composition warrants a film-grain texture. Specifically:

**Grain fires when ANY scene in the video has:**
- `era` = HISTORICAL, ANCIENT, or SYMBOLIC
- OR `mood` = reverent, mysterious, reflective, fearful, lonely
- OR `style` = CINEMATIC or DOCUMENTARY (not REALISTIC or MODERN)

**Grain does NOT fire when:**
- All scenes are era=MODERN + style=REALISTIC (clean, contemporary look)
- `OVERLAY_GRAIN_ENABLED=false` is set explicitly

**Grain is always whole-video when it fires** — not per-scene gated.
The time-gate approach used for mood overlays does not apply to grain.

---

## Implementation

### 1. Add `_should_apply_grain()` to `OverlayCompositor` in `overlay.py`

```python
# Eras and moods that warrant grain texture
_GRAIN_ERAS = {"HISTORICAL", "ANCIENT", "SYMBOLIC", "TRANSITIONAL"}
_GRAIN_MOODS = {"reverent", "mysterious", "reflective", "fearful", "lonely"}
_GRAIN_STYLES = {"CINEMATIC", "DOCUMENTARY"}

def _should_apply_grain(self, scenes: list[dict]) -> bool:
    """
    Returns True if ANY scene in the video warrants film grain.
    Checks era, mood, and style from scene visual metadata.
    """
    for scene in scenes:
        era = (scene.get("era") or "").upper()
        mood = (scene.get("mood") or "").lower()
        style = (scene.get("style") or "").upper()
        scene_type = scene.get("scene_type", "")

        if scene_type == "brand_card":
            continue

        if era in _GRAIN_ERAS:
            return True
        if mood in _GRAIN_MOODS:
            return True
        if style in _GRAIN_STYLES:
            return True

    return False
```

### 2. Add `OVERLAY_GRAIN_ENABLED` setting to `SharedSettings`

```python
overlay_grain_enabled: bool = Field(default=True, env="OVERLAY_GRAIN_ENABLED")
```

Add to `.env.example`:
```bash
OVERLAY_GRAIN_ENABLED=true  # set false to disable grain on all videos
```

### 3. Update `_apply_overlays()` in `pipeline.py`

Replace the unconditional grain application with:

```python
# Grain — conditional, whole-video, last in chain
if settings.overlay_grain_enabled and compositor._should_apply_grain(scenes):
    logger.info("Overlay: applying grain (whole-video)")
    _run_grain_pass(input_path, output_path, compositor)
else:
    logger.info("Overlay: grain skipped (no warranting scenes or disabled)")
    # rename input to output without grain pass
    input_path.rename(output_path)
```

Log line must clearly state whether grain was applied or skipped and why,
so it's auditable in the pipeline log.

---

## Tests

```python
def test_grain_fires_for_historical_era():
    scenes = [{"era": "HISTORICAL", "mood": "determined", "style": "DOCUMENTARY"}]
    compositor = OverlayCompositor(...)
    assert compositor._should_apply_grain(scenes) is True

def test_grain_fires_for_reverent_mood():
    scenes = [{"era": "MODERN", "mood": "reverent", "style": "REALISTIC"}]
    compositor = OverlayCompositor(...)
    assert compositor._should_apply_grain(scenes) is True

def test_grain_fires_for_cinematic_style():
    scenes = [{"era": "MODERN", "mood": "hopeful", "style": "CINEMATIC"}]
    compositor = OverlayCompositor(...)
    assert compositor._should_apply_grain(scenes) is True

def test_grain_skipped_for_all_modern_realistic():
    scenes = [
        {"era": "MODERN", "mood": "hopeful", "style": "REALISTIC"},
        {"era": "MODERN", "mood": "determined", "style": "REALISTIC"},
    ]
    compositor = OverlayCompositor(...)
    assert compositor._should_apply_grain(scenes) is False

def test_grain_skipped_for_brand_card_only():
    scenes = [{"era": "", "mood": "", "style": "", "scene_type": "brand_card"}]
    compositor = OverlayCompositor(...)
    assert compositor._should_apply_grain(scenes) is False

def test_grain_disabled_by_setting():
    # When OVERLAY_GRAIN_ENABLED=false, grain never applies
    # regardless of scene content
    # Mock settings.overlay_grain_enabled = False
    # Assert grain pass is not called
    pass

def test_grain_log_line_emitted():
    # When grain fires, log must contain "applying grain"
    # When grain skipped, log must contain "grain skipped"
    pass
```

---

## For This Video (Atma Theory — eagle/Bhagiratha/Vinoba Bhave)

This video has era=HISTORICAL, ANCIENT, SYMBOLIC scenes and
mood=reverent, mysterious, reflective throughout. Grain **will** fire —
which is correct. The change only prevents grain from appearing on
videos that are entirely contemporary/realistic in tone, where it would
look wrong.

---

## Do NOT change

- Mood overlay selection logic (`select_category()`)
- Time-gate approach for mood overlays
- `skip_overlays` global setting behaviour
- Audio pipeline
- Any validator, scene planner, or prompt template
- Test baseline — do not regress
