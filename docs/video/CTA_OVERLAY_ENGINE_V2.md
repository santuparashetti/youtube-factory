# CTA_OVERLAY_ENGINE.md

# Implementation Specification for Claude Code

## Objective

Implement a reusable **CTA Overlay Engine** as a dedicated stage in the
YouTube Factory pipeline.

The CTA system must be configuration-driven, reusable across channels,
visually consistent with the channel brand, and never hardcoded into
individual videos.

---

# Pipeline Position

```
Research
→ Script
→ Narration
→ Subtitles
→ Images / Video
→ BGM Mix
→ CTA Overlay Engine
→ End Screen
→ Final Render
```

CTA rendering occurs after subtitles/BGM generation and before the final
mux.

---

# Design Goals

- Reusable across all videos
- Brand-aware
- Configuration-driven
- Smooth cinematic animations
- Zero manual editing
- Subtitle-safe
- Context-aware
- Guaranteed to render — a video is never shipped silently without its
  configured CTA, even in edge cases where ideal placement isn't found

---

# Default Style (Atma Theory)

Avoid the standard YouTube red subscribe animation.

Use:

- Frosted glass panel
- Soft blur
- Rounded corners
- White typography
- Cyan / teal accent (#2EC5E8)
- Soft shadow
- Calm premium aesthetic

Animation:

- Fade in
- Gentle scale (0.95 → 1.0)
- Soft glow
- Fade out

Avoid:

- Bounce
- Flash
- Shake
- Loud effects

---

# CTA Templates

Support reusable templates:

- glass
- minimal
- atma
- premium

Each template owns: layout, base colors, typography, icons, animation,
sound.

Switching templates requires configuration only.

**Template vs. branding precedence:** a channel's `branding` block
overrides a template's colors and font wherever both are declared —
templates supply structural/animation defaults (layout, motion curve,
icon set), while `branding` always wins for accent color and typeface.
A template that wants to enforce its own look regardless of branding
must explicitly set `locked: true` on the relevant property; absent that,
branding always takes precedence. This precedence rule must be documented
alongside the template schema, not left implicit.

---

# CTA Cardinality

This engine renders **one CTA per video** by default (single insertion
point per the pipeline position above). Multi-CTA support (e.g. a
subscribe prompt near the midpoint plus a like-reminder near the end) is
out of scope for this version — the config schema below is intentionally
a single block, not a list. If multi-CTA becomes a requirement later, the
schema will need to change from an object to an array; this is a known
future extension point, not an oversight.

---

# Configuration

```yaml
cta:
  enabled: true
  template: atma_glass
  timing_mode: contextual
  fallback_timing: 65%
  duration: 6s
  min_pause_ms_for_full_cta: 3000   # below this, use compact_variant instead
  animation: smooth_fade
  show_like: true
  show_subscribe: true
  show_bell: true
  sound: meditation_chime
  max_placement_search_pct: 90      # give up searching for a safe pause
                                     # past this point in the video
```

---

# Context-Aware Timing

The CTA should not appear at a fixed timestamp whenever possible. Instead,
use existing pipeline metadata: ThoughtPauseRanges, subtitle timings,
narration timings.

**Search algorithm:**

1. Find the first insight-tier pause after the midpoint of the video.
2. Check if that pause is subtitle-safe (see Subtitle Safety below).
3. If safe → place CTA there.
4. If not safe → continue to the next insight-tier pause and repeat.
5. If no subtitle-safe insight-tier pause is found by
   `max_placement_search_pct` of video duration → fall back to
   `fallback_timing` (a fixed percentage position), regardless of
   subtitle state, and render the **compact variant** (see below) rather
   than skipping the CTA.

This distinguishes two separate failure modes that were previously
conflated:
- **No insight-tier pause exists** in the search window at all → this is
  the primary trigger for falling back to `fallback_timing`.
- **A pause exists but isn't subtitle-safe** → the engine keeps searching
  forward rather than immediately falling back, since a later pause is
  often still available before `max_placement_search_pct` is reached.

Never interrupt active narration. CTA fade-in only begins after a
narration sentence boundary.

**Duration vs. pause length:** `duration: 6s` is the target for a
full-size CTA landing in a pause of at least `min_pause_ms_for_full_cta`.
If the matched pause is shorter than that threshold (e.g. a 1800–2500ms
insight-tier pause), the CTA does not force its full 6s duration through
narration resumption. Instead:
- Full CTA is used only when the pause window comfortably fits the full
  animation (fade in + hold + fade out) before narration resumes.
- Otherwise, the engine renders the **compact variant**: a smaller,
  corner-anchored badge with a shorter fade cycle that fits within the
  available pause, and does not block narration resumption if the pause
  ends early.

---

# Subtitle Safety

The CTA must never cover subtitles.

Requirements:

- Read subtitle timing and subtitle bounding boxes.
- If subtitles are visible, automatically reposition the CTA or reduce
  its size.
- Respect title-safe and subtitle-safe regions.
- Prefer bottom-center placement only when subtitle area is free.
- Otherwise move to upper-left, upper-right, or another configured safe
  zone.
- If no safe placement exists at a given pause, treat that pause as
  unsuitable and continue the search per the Context-Aware Timing
  algorithm above — do not silently skip the CTA for the whole video.

Subtitle readability always has higher priority than CTA visibility. The
one guaranteed exception is the final fallback step (`fallback_timing` +
compact variant), which renders regardless of subtitle state to preserve
the "always ships" guarantee — using the smallest, least-intrusive
footprint (corner badge, no panel background) specifically because it
cannot guarantee subtitle clearance at that point.

---

# Audio

Use subtle sounds only: meditation bell, soft wooden click, gentle chime.

**Coordination with BGM:** the BGM Adaptive Mixing Engine ducks music
only around narration, not around CTA sound cues — these are two
independent systems. Before playing the CTA sound, this engine must:

1. Check the BGM gain envelope at the CTA's timestamp.
2. If BGM is mid-swell (recovering toward baseline during the same
   insight-tier pause the CTA is using), apply a brief secondary duck to
   BGM (using the same smooth envelope style as the BGM engine, not an
   abrupt cut) for the CTA sound's duration, then let BGM continue its
   recovery afterward.
3. This secondary duck is the CTA engine's responsibility to trigger, not
   a change to the BGM engine's own logic — it composites its automation
   on top of the existing BGM gain curve rather than modifying it
   upstream.

CTA audio must always sit below both narration (silent at this point,
since CTA only fires in pauses) and background music level.

---

# Branding

Support per-channel branding:

```yaml
branding:
  accent_color: "#2EC5E8"
  font: Outfit
  logo: assets/logo.png
```

The CTA automatically inherits active channel branding, per the
precedence rule defined under CTA Templates above.

---

# ReviewPipeline Validation

Verify:

- correct timing
- appears during a valid, subtitle-safe pause (or valid fallback placement)
- no narration interruption
- no subtitle overlap
- fully visible for its full configured duration (full or compact variant)
- branding loaded and precedence applied correctly
- animation completed
- audio acceptable and correctly ducked against BGM

**On validation failure:** unlike the BGM engine, CTA placement failure
does not trigger a remix-style retry loop — the deterministic search
algorithm above already accounts for placement failure (moving to the
next pause, then falling back). If validation still fails after that
(e.g. animation asset corrupted, branding failed to load), the engine:

1. Retries once with the same placement but re-rendering the overlay
   asset.
2. If it still fails, falls back to the `minimal` template (lowest
   asset/animation complexity) at the same placement.
3. If that also fails, the CTA stage fails explicitly and blocks final
   mux — it does not silently produce a final video with no CTA. Failure
   is reported in the CTA review report with a clear reason code, the
   same way the BGM engine reports `max_attempts_reached`.

---

# Incremental Build

Changing CTA rebuilds only: CTA overlay, final render.

Reuse narration, subtitles, images, and BGM.

---

# Deliverables

Generate:

- CTA overlay asset
- CTA timing metadata (including which placement path was used: primary
  contextual, fallback timing, full variant, or compact variant)
- CTA review report (including reason codes on any retry/fallback taken)
- Final rendered video

---

# Implementation Requirements

- Preserve backward compatibility.
- Reuse existing pipeline.
- Configuration-driven.
- Use existing ThoughtPauseRanges and subtitle metadata.
- Do not duplicate timing logic.
- Add unit and integration tests, including tests for: no-safe-pause
  fallback, short-pause compact-variant switch, BGM secondary-duck
  coordination, and the three-step validation-failure escalation.
- Run Ruff, MyPy and tests.
- Update documentation.
- Do not pause for approval.
