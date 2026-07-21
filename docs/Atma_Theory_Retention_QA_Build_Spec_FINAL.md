# Atma Theory — Retention QA System — Build Spec for Kilo Code

## Objective

Implement retention/quality rules from `Video_Retention_Standards_v1.md`
into the existing `video_core` / `ytfactory` pipeline as **two gates**:

1. **Pre-render gate** — checks the script + scene plan *before* image
   generation, TTS, and render. Cheap, fast, blocks bad scripts early.
2. **Post-render audit** — checks the final rendered video (visuals,
   motion, text timing, audio) *after* render, before upload. Catches
   what only exists once assets are real (actual shot duration, actual
   text-on-screen time, actual motion).

Both feed the same `RetentionScore` (0–100, upload gate at ≥85, see
`Video_Retention_Standards_v1.md` §Quality Gate for weights).

**Integrate into the existing pipeline — do not build a parallel system.**
Mark points below as `[INTEGRATE: ...]` where you should locate and hook
into current code (factory pattern, `SharedSettings`, existing subtitle
generation, existing image QA stack with `ImageReviewEngine` /
MiniCPM-V, existing TTS spiritual-pause timing, chapters capping, CTA
overlay diagnostics). Reuse existing subtitle/timestamp/scene metadata
wherever it already exists rather than re-deriving it.

---

## ⚠️ Corrections after reviewing MASTER_CONTEXT_UPDATED.md (read this first)

Several things this spec originally proposed as new already exist.
Kilo should wire into these, not rebuild them:

- **Motion engine already exists.** `video_core/cinematic/` (`motion.py`,
  `transitions.py`, `profiles.py`, `effects.py`, `config.py`) +
  `build_zoompan_filter()` in `video_core.cinematic.ffmpeg_filters`,
  used by `FFmpegRenderer` / `render_continuous()`. **§1.4a Tier 1
  (zoom/pan/parallax/push) does not need to be built — `assign_motion`
  should call into this existing engine.** Only Tier 2 (fog/dust/light
  rays/particles, asset-overlay based) is still a real gap — nothing in
  MASTER_CONTEXT mentions overlay compositing. Also: respect the
  documented **"duration bug"** — `zoompan` outputs `d` frames *per
  input frame* when fed a video stream without a `trim=` filter first
  (outputs `dur² × fps` seconds). Any duration extension for emotional
  holds (P5) must go through the existing trim-before-zoompan fix, not
  a fresh filter chain.
- **Hard-reject mechanism already exists.** Use `PipelineAbort(stage, reason)`
  from `ytfactory.shared.pipeline_status` for the Frame Naming Gate
  (§1.1) hard-reject, gated by `STOP_ON_QUALITY_GATE_FAILURE` (default
  true) — not a bespoke return-list convention as originally drafted.
- **`ValidationRunner` already runs 12 validators**, including `motion`
  and `story` sections. New rules (frame-naming gate, bridge check,
  static-shot, emotional-hold sequencing, text-overlay duration) should
  be added as new rule IDs *inside* `review/validation/rules/story.py`
  and `review/validation/rules/motion.py`, following the existing
  naming convention (e.g. `HUM_001`, `SUBT_007`, `BGM_008`) — not a
  standalone QA module.
- **Retention rules already exist in script generation.**
  `DocumentaryScriptEnhancerPipeline` Pass 2 already has 10 Viewer
  Retention Rules, including "(4) Delay branding (never interrupt
  opening hook)" and "(5) Maintain curiosity (raise question, delay
  answer, reward later)" — plus a Narrative Score self-assessment
  (Hook/Story Density/Curiosity/Emotional Rhythm/Accessibility,
  threshold 8.5). **§1.3's Hook/Re-hook/Transition prompts should
  sharpen rule (4) and (5) — e.g. rule (4) should explicitly cover
  naming the *frame/structure* ("four truths"), not just channel
  branding — rather than adding parallel generator prompts.**
- **`scene-plan.json` is the real central artifact** — `scenes[].visual_prompt`,
  `scenes[].narration`, `scenes[].duration_seconds`. Map `Scene` (§0)
  onto these real fields instead of inventing a parallel structure.
- **Working Rules apply to Kilo too**: architecture review + integration
  plan first, wait for approval, before implementing — don't let "build
  everything in an hour" skip that step given how much of this spec
  turned out to already exist. `.env` changes: comment out the old line,
  add the new value on the next line, never overwrite.
- **Exact pipeline hook points (from latest MASTER_CONTEXT), confirmed
  final:** `START → research_agent/script_enhancer → script_writer →
  human_review_script → scene_planner → human_review_scenes →
  generate_scene_assets (per-scene parallel) → video_renderer →
  video_concatenator → cta → quality_review → remediation → publish → END`.
  - **Pre-render gate (§1) belongs between `scene_planner` and
    `human_review_scenes`** — run it right before the human checkpoint,
    so the reviewer sees an already-checked scene plan instead of
    catching frame-naming/bridge/motion issues manually.
  - **Post-render audit (§2) belongs inside the existing `quality_review`
    stage**, not as a new stage — it already sits right before
    `remediation` and `publish`, which is exactly where these checks
    need to block upload. Add the new rules to `ValidationRunner`
    (motion.py/story.py, per the corrections above) so they run as part
    of `quality_review`, and let failures flow into the existing
    `remediation` stage rather than a separate reject path.
  - Vision provider note (unrelated to retention QA, but corrects an
    earlier assumption): active local vision provider is now
    **Qwen2.5-VL-3B** via llama.cpp, not MiniCPM-V 2.6 — irrelevant to
    this spec's logic but worth knowing if any new check calls into the
    vision QA stack.

---

## 0. Shared Data Models

```python
from dataclasses import dataclass, field
from enum import Enum

class EmotionalIntensity(Enum):
    NORMAL = "normal"
    EMOTIONAL = "emotional"
    PEAK = "peak"
    REFLECTION = "reflection"

@dataclass
class ScriptSegment:
    text: str
    start_time: float | None = None   # populated after TTS
    end_time: float | None = None
    is_hook: bool = False
    is_rehook: bool = False
    is_frame_label: bool = False      # names the theme/structure, e.g. "four truths"
    is_bridge: bool = False           # reflection/question line connecting story -> theme
    emotional_intensity: EmotionalIntensity = EmotionalIntensity.NORMAL

@dataclass
class Scene:
    index: int
    start_time: float
    end_time: float
    duration: float
    pose: str | None = None
    composition: str | None = None
    motion_type: str | None = None    # zoom/pan/parallax/push/fog/dust/particles/none
    text_overlay: str | None = None
    text_reveal_segments: list[str] = field(default_factory=list)
    hold_required: bool = False       # True if scene follows a PEAK emotional segment
    linked_segment: ScriptSegment | None = None

@dataclass
class RetentionScoreResult:
    total: float
    breakdown: dict[str, float]       # category -> score
    violations: list[str]             # human-readable, each tagged with rule id (P1a, P5, etc.)
    passed: bool                      # total >= 85 and no hard-reject violations
```

`[INTEGRATE]`: map `ScriptSegment`/`Scene` onto whatever your current
scene-planner / script-generator objects already are — add fields
rather than replacing the class if one exists.

---

## 1. Pre-Render Gate (script + scene plan level)

### 1.1 Frame Naming Gate — rule **P1a**

```python
def check_frame_naming_gate(segments: list[ScriptSegment]) -> list[str]:
    """
    Reject if any segment with is_frame_label=True appears before the
    first segment with is_rehook=True.
    Returns list of violation strings (empty = pass).
    """
```
- `is_frame_label` detection: segment mentions the video's structural
  frame (e.g. "four truths", "three lessons", channel/series name).
  `[INTEGRATE]`: if you already tag segments by type during script
  generation, reuse that; otherwise this needs a simple classifier
  (keyword match against the script's declared frame count/name is
  sufficient — doesn't need an LLM call).
- Hard reject, not a score deduction — block generation from proceeding.

### 1.2 Bridge Requirement — rule **P4 extension**

```python
def check_bridge_requirement(segments: list[ScriptSegment]) -> list[str]:
    """
    Walk segments in order. If a segment marked as a story resolution
    is immediately followed by a segment marked is_frame_label=True
    with no is_bridge=True segment between them, flag a violation.
    """
```
- Needs `ScriptSegment` to carry a `resolves_story: bool` flag from the
  script generator — add this alongside `is_frame_label` / `is_bridge`.
- Score deduction under "Story Flow" (weight 20) rather than hard
  reject — this is a quality issue, not a broken video.

### 1.3 Hook / Re-hook / Transition Generation

`[INTEGRATE]`: wherever the current script generator calls the LLM,
add these as system-prompt fragments (not new endpoints):

```
HOOK_GENERATOR_PROMPT = """
Generate the opening 10-20 seconds of a video script.
Rules:
- No channel introduction, no "welcome to", no naming the video's frame/structure.
- Must open with one of: unexpected story, contradiction, powerful
  question, shocking fact, emotional situation.
- Introduce the mystery within the first 10 seconds.
Template: "Imagine... / But... / Because..."
"""

REHOOK_INJECTOR_PROMPT = """
Given a script, insert a one-sentence curiosity hook every 30-45
seconds of estimated narration time. Never let a gap exceed 45 seconds.
Do not repeat rehook phrasing within the same script.
"""

TRANSITION_GENERATOR_PROMPT = """
Replace flat "Truth N" / "Lesson N" style transitions with:
Story -> Reflection -> Question -> Next Story.
If a story's resolution is followed by a return to the overarching
theme, you MUST insert a bridge line (reflection or question) between
the resolution and the theme recap. Never cut directly from a story's
resolution to a theme-label sentence.
"""
```

### 1.4a Motion Engine V2 — why the review still caught a static shot, and the fix

The existing `video_core/cinematic/` engine (zoompan-based) isn't the
gap — it's that nothing *enforced* it lands on every scene, and what
it does apply is often too subtle to read as motion. That's exactly
how a static shot (0:02–0:09) got through: the engine existed, but
nothing checked its actual output before upload. "Upgrade" here means
two separate things, and both are needed — a better engine AND an
enforcement gate, because a better engine alone doesn't fix a missing
QA check, and a QA check alone doesn't fix weak motion.

**A. Stronger motion, not just present motion**
- Move from single-parameter zoompan (one zoom rate) to **combined
  motion**: zoom + pan together by default, not zoom *or* pan. A pure
  slow zoom on a static composition reads as barely-there; zoom+pan
  together reads as intentional camera movement.
- **Motion intensity tied to emotional_intensity** (§0 model), not
  fixed: `NORMAL`→subtle (small zoom+pan), `EMOTIONAL`→moderate,
  `PEAK`→slow deliberate push (paired with the hold from §1.4),
  `REFLECTION`→slow drift. Reuse existing `profiles.py` in
  `video_core/cinematic/` if it already has an intensity concept —
  `[INTEGRATE]` check before adding a new one.
- **Motion variety across consecutive scenes** — same rule shape as
  pose variety (§1.4): reject/flag if the same motion type+direction
  (e.g. "zoom in, center") repeats 3+ scenes running. Add
  `check_motion_variety(scenes)` alongside `check_pose_variety`.
- Tier 2 (fog/dust/light rays/particles overlay compositing) still
  applies as previously scoped — layer it on top of the stronger base
  motion for peak/emotional scenes specifically, where the extra depth
  earns its cost; not required on every scene.

**B. Enforcement — the actual missing piece**
This is the real root cause: `detect_static_shots` (§2) needs to run
and actually block upload, not just log. Concretely:
- Wire `detect_static_shots` as a new rule in
  `review/validation/rules/motion.py` (per the corrections section
  above) — call it e.g. `MOTION_00X` — and make it a **hard-reject**
  via `PipelineAbort`, not a score deduction. A static shot isn't a
  quality nuance, it's the exact defect the review flagged.
- Threshold should key off *perceptible* motion, not just pixel delta
  — a very slow zoom can pass a naive frame-diff check while still
  reading as static to a viewer. Calibrate the frame-diff threshold
  against the 0:02–0:09 clip specifically as ground truth (§4
  acceptance tests) — if that clip doesn't get flagged with default
  thresholds, the threshold is too loose, not the detector wrong.
- This check must run **post-render**, since motion strength depends
  on the actual rendered output, not the scene-plan's `motion_type`
  label — a scene can be labeled `zoom` in `scene-plan.json` and still
  render close to static if the zoom rate config was too conservative.

```python
def assign_motion(scenes: list[Scene]) -> None:
    """
    Any scene >4s gets combined zoom+pan motion assigned by default
    (never a single-parameter zoom alone), with intensity keyed off
    linked_segment.emotional_intensity. Tier 2 overlay only added on
    top for EMOTIONAL/PEAK scenes where an asset exists — see §1.4a.
    Never leave motion_type=None on a scene >4s.
    """

def check_motion_variety(scenes: list[Scene]) -> list[str]:
    """Flag if the same (motion_type, direction) pair repeats across 3+ consecutive scenes."""
```

### 1.4b Scene Plan Checks (pre-render, before image gen)

```python
def check_scene_durations(scenes: list[Scene]) -> list[str]:
    """Flag scenes outside 2-5s, unless hold_required=True (emotional exception)."""

def assign_hold_required(scenes: list[Scene], segments: list[ScriptSegment]) -> None:
    """
    For each scene whose linked_segment.emotional_intensity == PEAK,
    set hold_required=True and extend duration by +1.5-2.0s.
    Sequencing rule: hold happens on the CURRENT scene before any
    pose/composition change — do not let the hold overlap a scene cut.
    Concretely: if scene[i].hold_required, scene[i+1].pose must differ
    from scene[i].pose only AFTER scene[i].duration has elapsed, never
    mid-hold. (I.e. don't shorten the hold to fit a pose change.)
    """

def check_pose_variety(scenes: list[Scene]) -> list[str]:
    """Reject if the same pose (esp. 'thinking') repeats across 3+ consecutive scenes."""

def check_composition_variety(scenes: list[Scene]) -> list[str]:
    """Flag if 'center' composition repeats 3+ consecutive scenes."""

def plan_text_reveal(scene: Scene) -> None:
    """
    If scene.text_overlay is set and scene.duration > 5s, split into
    scene.text_reveal_segments (word/phrase groups), each shown 1-2s,
    instead of one static block for the full duration.
    """
```

`[INTEGRATE]`: hook `assign_hold_required` and `assign_motion` into
wherever your scene planner currently runs, before it hands off to
image generation — this is Phase 2/3 boundary in the existing
pipeline.

### 1.5 Pre-Render Gate Entry Point

```python
def run_pre_render_gate(segments: list[ScriptSegment], scenes: list[Scene]) -> RetentionScoreResult:
    """
    Runs 1.1-1.4 checks. Hard-reject on frame naming gate failure.
    Score deductions for everything else. Returns result; pipeline
    should not proceed to image/TTS generation if passed=False.
    """
```

---


## 2. Post-Render Audit (final video level)

This operates on the rendered video file + its subtitle/timing
metadata (reuse whatever the pipeline already emits — don't re-derive
timestamps from scratch if subtitle files already carry them).

```python
@dataclass
class PostRenderFindings:
    static_shot_violations: list[tuple[float, float]]   # (start,end) > 4s no motion
    text_overlay_violations: list[tuple[float, float, str]]  # (start,end,text) held too long
    missing_hold_violations: list[tuple[float, float]]  # peak moment with no pause before cut
    rehook_gap_violations: list[tuple[float, float]]    # gap > 45s between hooks
    frame_naming_violations: list[tuple[float, float]]  # frame label found before first rehook, by actual timestamp

def detect_static_shots(video_path: str, threshold_seconds: float = 4.0) -> list[tuple[float, float]]:
    """
    Frame-diff based: sample frames at ~2fps, compute per-region delta,
    flag continuous windows where delta stays below a motion threshold
    for > threshold_seconds. [INTEGRATE]: use existing ffmpeg/cv2
    dependency already in the render pipeline if present, don't add
    a new one.
    """

def detect_text_overlay_duration(video_path: str) -> list[tuple[float, float, str]]:
    """
    [INTEGRATE]: if the CTA/text overlay engine already tracks overlay
    timing as render metadata (it likely does, given CTA Overlay Engine
    V2), read that directly instead of doing OCR on frames — much
    cheaper and more reliable. Flag any single overlay block active > 5s.
    """

def detect_missing_holds(video_path: str, segments: list[ScriptSegment], scenes: list[Scene]) -> list[tuple[float, float]]:
    """
    Cross-reference segments where emotional_intensity == PEAK against
    the actual scene cut timestamps in the rendered video. Flag if a
    scene cut/pose-change occurs within 1.5s of a peak line ending
    (i.e. the hold didn't survive render).
    """

def detect_rehook_gaps(segments: list[ScriptSegment]) -> list[tuple[float, float]]:
    """Using actual TTS-timed segment timestamps, flag any gap >45s between is_rehook=True segments."""

def detect_frame_naming_violation(segments: list[ScriptSegment]) -> list[tuple[float, float]]:
    """Same as pre-render check (1.1) but against real timestamps, as a final safety net in case script-level check was bypassed."""

def run_post_render_audit(video_path: str, segments: list[ScriptSegment], scenes: list[Scene]) -> RetentionScoreResult:
    """Runs all detect_* above, aggregates into RetentionScoreResult using the same weighting as pre-render gate."""
```

---

## 3. Combined Scoring

```python
CATEGORY_WEIGHTS = {
    "hook": 30,
    "story_flow": 20,       # includes P1a frame-gate + P4 bridge requirement
    "visuals_editing": 20,  # includes motion, static shots, text reveal
    "audio_pacing": 15,
    "ending": 15,
}

def combine_scores(pre_render: RetentionScoreResult, post_render: RetentionScoreResult) -> RetentionScoreResult:
    """
    Pre-render gate must pass (or be force-overridden) before post-render
    audit runs at all — no point rendering a script that already fails
    the frame-naming gate.
    Final score = post_render result (it reflects reality); pre_render
    result is used only as the go/no-go for entering render.
    Upload gate: final total >= 85 AND no hard-reject violations.
    """
```

---

## 4. Acceptance Test Cases

Use the actual review findings as regression tests once built:

| Rule | Timestamp | Expected detector | Expected result |
|---|---|---|---|
| P1a | 0:10–0:21 | `detect_frame_naming_violation` | violation flagged (frame label before first rehook) |
| P4 bridge | 1:54–2:02 | `check_bridge_requirement` (pre-render) | violation flagged (no bridge segment) |
| P5 sequencing | 3:27–3:32 | `detect_missing_holds` | violation flagged (cut within 1.5s of peak line) |
| P7/P17 motion | 0:02–0:09 | `detect_static_shots` | violation flagged (>4s no motion) |
| P11/P20 text | 1:35–1:45 | `detect_text_overlay_duration` | violation flagged (10s single overlay) |

Wire these five as unit/regression tests against the actual video
referenced in the review, if the file is available — that validates
detectors against ground truth before trusting them on new output.

---

## 5. Suggested Build Order (dependency-driven, not time-boxed)

1. Data models (§0) — everything else depends on these.
2. Pre-render gate checks (§1.1–1.4) — cheapest, catches most issues before spending render cost.
3. Prompt fragments (§1.3) — wire into existing script-gen LLM calls.
4. Pre-render gate entry point (§1.5) — block pipeline on hard-reject.
5. Post-render detectors (§2) — start with `detect_text_overlay_duration` (likely free, metadata-based) and `detect_rehook_gaps` (timestamp-based, no CV needed) before the CV-heavy `detect_static_shots`.
6. Combined scoring (§3).
7. Acceptance tests (§4) against the reviewed video.

---

## Notes for Kilo

- Don't duplicate anything the existing image QA stack
  (`ImageReviewEngine`, MiniCPM-V) or CTA overlay engine already does —
  read their outputs where possible instead of re-analyzing frames.
- Preserve existing TTS spiritual-pause timing logic; the emotional
  hold (§1.4, P5) is a *scene visual* hold, separate from narration
  pause timing — don't conflate the two.
- The motion engine (§1.4a) is net-new — no zoom/pan/overlay library
  currently exists. Ship Tier 1 (parametric, ffmpeg-only) first; Tier 2
  (fog/dust/particles/light-rays) waits on someone sourcing a small
  overlay-asset library, which is a manual task, not a coding one.
- Full rule reference: `Video_Retention_Standards_v1.md` and
  `Atma_Theory_Retention_Implementation_Plan_v1.1.md` (attached
  separately) — this spec is the build-ready subset of those.
