The latest motion improvements are visible, but the rendered video still does not achieve the intended cinematic effect.

Do NOT redesign the rendering architecture.

Do NOT introduce a new motion engine.

Use the existing motion pipeline, camera movement system, FFmpeg filters, easing functions, renderer implementation, and motion specifications already present in the repository as the source of truth.

Your task is to determine why the rendered motion is not smooth, not sustained, and why zoom effects appear to be missing.

Implement only the smallest architecture-compliant fixes.

---

# Current Problems

## 1. Camera motion is not smooth

Movement appears to:

- start
- move briefly
- slow or pause
- continue again

Instead of one continuous camera movement, the animation feels like small discrete steps.

The camera should glide smoothly throughout the scene.

---

## 2. Motion ends too early

Many scenes stop moving well before the scene ends.

The remaining frames become visually static.

Expected:

Motion should continue naturally until the scene transitions.

Target:

Motion duration should cover approximately 95–100% of the visible scene duration.

---

## 3. Zoom effect appears missing

In the latest rendered video I do not observe meaningful zoom movement.

Expected:

Every scene assigned a zoom-based motion preset should have clearly visible and continuous zoom.

Examples:

- slow push-in
- slow pull-out
- continuous dolly-in
- continuous dolly-out

The zoom should be obvious to viewers while remaining smooth and cinematic.

Determine whether:

- zoom presets are not being selected
- zoom values are too small
- zoom values are being clamped
- zoom expressions are incorrect
- FFmpeg zoompan expressions are not changing over time
- another transform overrides zoom
- renderer defaults cancel zoom
- interpolation removes zoom progression

---

## 4. Motion feels too conservative

Although pans are more noticeable, overall movement is still restrained.

Static AI-generated images should feel alive through continuous cinematic movement.

Motion should be immediately noticeable without becoming distracting.

---

# Investigation Tasks

Trace the complete motion pipeline:

Scene metadata

↓

Motion preset selection

↓

Motion parameter generation

↓

Zoom generation

↓

Pan generation

↓

Keyframe generation

↓

FFmpeg filter generation

↓

Rendered video

Determine exactly where motion loses intensity or stops.

---

# Verify Motion Presets

For every rendered scene report:

- selected motion preset
- zoom enabled (Yes/No)
- zoom start
- zoom end
- zoom delta
- pan X start/end
- pan Y start/end
- duration
- easing
- interpolation

Confirm that the rendered output matches these values.

---

# Verify FFmpeg Expressions

Inspect the generated FFmpeg filters.

Verify that:

- zoom changes continuously every frame
- pan coordinates change continuously every frame
- expressions remain dynamic until the scene ends
- expressions never become constant prematurely

If zoompan is used, verify the generated expressions mathematically rather than visually.

---

# Verify Timing

Motion should remain active throughout the scene.

Verify:

- motion start
- motion end
- easing duration
- interpolation duration

Motion must not terminate before the scene transition.

---

# Motion Debug Report (Required)

Generate a detailed per-scene motion diagnostics report.

For every scene include:

- scene number
- scene duration
- selected motion preset
- zoom enabled
- zoom start value
- zoom end value
- total zoom delta
- pan X start/end
- pan Y start/end
- easing function
- interpolation method
- motion duration
- generated FFmpeg filter
- generated zoompan expression (if applicable)
- any clamping applied
- any normalization applied
- any safe-area adjustments applied
- final render transform

Highlight any discrepancies between:

- intended motion
- generated motion
- rendered motion

If zoom was expected but not rendered, identify the exact stage where it was lost.

---

# Validation

Render a short debug sample (5–10 seconds is sufficient) using the corrected motion settings.

Verify that:

- zoom is clearly visible
- motion is continuous
- no stepping or pauses occur
- movement lasts until the scene transition
- FFmpeg output matches the generated motion parameters

---

# Deliverables

## 1. Root Cause

Explain exactly why:

- motion feels jerky
- motion stops early
- zoom is missing or barely visible

Reference the implementation.

Do not speculate.

---

## 2. Motion Analysis

For every motion preset provide:

- zoom range
- pan range
- duration
- easing
- generated FFmpeg expressions

Highlight any scenes where zoom was expected but not actually applied.

---

## 3. Required Fixes

Implement only the minimum architecture-compliant changes.

Do not redesign the renderer.

Do not modify unrelated systems.

---

## 4. Verification

After implementing the fixes, verify that:

- every scene has continuous motion
- zoom presets produce clearly visible zoom
- camera movement remains smooth from the first frame until the scene transition
- no motion terminates prematurely
- no FFmpeg expression becomes static before the scene ends
- rendered output matches the intended motion parameters

---

# Success Criteria

The final rendered video should feel like a professionally animated documentary rather than a slideshow.

Every static AI-generated image should remain visually alive through continuous cinematic motion.

The camera should glide naturally throughout each scene with:

- clearly visible zoom
- continuous pan
- smooth interpolation
- motion sustained for nearly the full scene duration

The rendered output should faithfully match the motion generated by the pipeline.