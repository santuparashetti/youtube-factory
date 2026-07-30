# YouTube Factory — Motion Generation Architecture: Technical Review

===========================================================
## 1. PIPELINE OVERVIEW
===========================================================

There are **two parallel pipeline implementations** in this codebase that both reach the same cinematic engine. Motion is **not** an AI-generation step — it is a deterministic, rule-based post-processing pass applied to already-rendered static images.

### Path A — Direct-call pipeline (`BuildPipeline` / `VideoPipeline`, used by `ytfactory build`, `ytfactory render`)

```
Script (script.md)
  ↓
ScenePipeline.run()                          src/ytfactory/scenes/pipeline.py
  → LLM breaks script into scenes            (narration, duration_seconds, visual_prompt draft)
  → ImagePromptEngineV4.enrich_scenes_with_shots()   assigns shot_type (image framing, NOT motion)
  → LLM Phase-2 call generates final visual_prompt per scene (STORYBOARD_HEADER-prefixed)
  ↓
ImagePipeline.run()                          src/ytfactory/images/pipeline.py
  → calls image provider (Gemini/HuggingFace) → scene-NNN.png
  → per-scene vision QA gate
  ↓
VoicePipeline.run() → CaptionPipeline.run()   audio + subtitles per scene
  ↓
VideoPipeline.run()                          src/ytfactory/video/pipeline.py
  → MotionPlanner().plan(scenes, profile)             ← "Motion Planner" (rule-based, no LLM)
  → TransitionPlanner().plan(scenes, profile)
  → EffectsPlanner().plan(scenes, profile)
  → MotionRebalancer().rebalance(scenes)
  → SceneRepository().save_scenes(...)                persists motion/transition/effects back to scene-plan.json
  → FFmpegRenderer.render() per scene → scene-NNN.mp4
  → FFmpegRenderer.render_continuous() → single filter_complex pass → final.mp4
  ↓
ReviewPipeline.run()                         src/ytfactory/review/pipeline.py
  → MotionValidator (MOT_001–006)                     ← "Motion QA" (post-render, rule-based)
  ↓
Video Generation = DONE at final.mp4 (no separate "Video Generation" AI step exists)
```

### Path B — LangGraph pipeline (`agents/graph.py`, YouTube-URL entry point)

```
composer → generate_scene_assets (parallel fan-out: image + audio + subtitle per scene)
  ↓
video_renderer_node                          src/ytfactory/agents/nodes/video_renderer.py
  → MotionPlanner → TransitionPlanner → EffectsPlanner → MotionRebalancer   (identical classes, same call order as Path A)
  → FFmpegRenderer.render() per scene
  ↓
video_concatenator → cta → quality_review_node (MotionValidator runs here too)
```

**Where each component starts/ends, precisely:**

| Component | Starts | Ends |
|---|---|---|
| Scene Planner | LLM script breakdown | `scene-plan.json` written with narration/duration/visual_prompt/shot_type |
| Visual Prompt Generator | *is a sub-phase inside Scene Planner*, not a separate stage | `visual_prompt` field finalized per scene |
| Motion Planner | reads `scene["narration"]`, `scene["duration_seconds"]`, `scene["scene_type"]` | writes `scene["motion"]` dict |
| Transition Planner | reads emotion + scene_type | writes `scene["transition_in"]` / `scene["transition_out"]` |
| Effects Planner | reads `scene["motion"]["emotion"]` | writes `scene["effects"]` |
| Motion Rebalancer | reads final `scene["motion"]["motion_type"]` sequence | may overwrite `motion_type` in-place to break long runs |
| Motion QA | reads rendered `final.mp4` + scene list | emits `MOT_001–006` ValidationResult objects |
| "Video Generation" | there is no AI video-generation call — FFmpeg (`libx264`) encodes the image+audio+filter chain directly | `final.mp4` |

**Important correction to the assumed diagram:** there is no separate "Motion Prompt Generator" stage and no pre-render "Motion QA" gate before video generation. Motion QA is a **post-render** validator category (runs after `final.mp4` exists), not a pre-generation gate.

===========================================================
## 2. MOTION ARCHITECTURE
===========================================================

**How motion is generated:** Purely algorithmic. Narration text is scored against a keyword lexicon to classify a dominant emotion (12 categories). The emotion is looked up in a per-profile table to get a `(motion_type, scale_tier)` pair. That pair is resolved into six normalized geometry numbers (`start_scale`, `end_scale`, `anchor_x/y`, `drift_x/y`) which are converted into an FFmpeg `zoompan` filter expression at render time. **No LLM, no vision model, and no motion-specific AI model is ever called.**

**Classes responsible:**
- `MotionPlanner` (`video_core/cinematic/motion.py`) — emotion → motion type → geometry
- `TransitionPlanner` (`video_core/cinematic/transitions.py`) — scene-boundary fade/cut selection
- `EffectsPlanner` (`video_core/cinematic/effects.py`) — color grade / vignette / grain / blur
- `MotionRebalancer` (`video_core/cinematic/rebalancer.py`) — post-pass variety enforcement
- `FFmpegRenderer` (`ytfactory/video/ffmpeg.py`) — turns all of the above into actual `-vf` filter strings and invokes `ffmpeg`

**Agents involved:** None, in the LLM-agent sense. The only "agent" touchpoints are the two orchestration wrappers that call these classes in sequence: `video_renderer_node` (LangGraph) and `VideoPipeline.run()` (direct-call). Neither one is itself an LLM agent — both are plain Python glue.

**Prompts used:** None. There is no text prompt for motion — see Section 3/4.

**Models used:** None (no ML model of any kind). The only "model" involved anywhere upstream is the LLM used by the Scene Planner to write narration/visual_prompt, and the diffusion/vision models used by Image Generation — neither is in the motion critical path.

**Providers used:** None — `video_core/providers/` has no "video" or "motion" provider type (only `llm`, `search`, `image`, `tts`, `vision`). Motion is local computation + a local `ffmpeg` binary invoked via `subprocess`.

**Information flow between components:**

```
narration (str) ─────────────┐
scene_position (float) ──────┼──▶ classify_scene()  (video_core/providers/tts/emotion.py)
                              │       — SAME classifier used by TTS prosody —
                              ▼
                    EmotionProfile.emotion.value  (e.g. "curiosity")
                              │
                              ▼
        profile.motion_map[emotion] → (motion_type, scale_tier)
                              │
                              ▼
        _resolve_motion(motion_type, scale_tier, cfg, index, duration)
                              │
                              ▼
                    MotionSpec  →  scene["motion"] (dict)
                              │
                              ▼
        MotionRebalancer  (may swap motion_type if run-length ≥ 3)
                              │
                              ▼
        build_zoompan_filter(w, h, fps, scene["motion"], duration)
                              │
                              ▼
                    FFmpeg -vf filter string  →  subprocess.run(["ffmpeg", ...])
```

### Architecture diagram

```
┌─────────────────┐     narration      ┌───────────────────────┐
│  Scene Planner   │ ─────────────────▶│  classify_scene()      │  (shared w/ TTS prosody)
│  (LLM)           │                   │  video_core/providers/  │
└─────────────────┘                    │  tts/emotion.py         │
        │ scene_type,                  └───────────┬─────────────┘
        │ duration_seconds                          │ Emotion (1 of 12)
        ▼                                            ▼
┌──────────────────────────────────────────────────────────────┐
│                        MotionPlanner                          │
│  profile (draft|balanced|cinematic|premium) → motion_map      │
│  → (motion_type, scale_tier) → _resolve_motion() → MotionSpec  │
└───────────────────────────┬────────────────────────────────────┘
                             │ scene["motion"]
                             ▼
┌──────────────────────────┐   ┌──────────────────────────┐
│   TransitionPlanner       │   │     EffectsPlanner        │
│ emotion-pair → fade type  │   │ emotion → color grade     │
└──────────────┬────────────┘   └────────────┬───────────────┘
               │ transition_in/out            │ effects
               ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      MotionRebalancer                          │
│  breaks runs of same motion_type ≥ 3 consecutive scenes         │
└───────────────────────────┬──────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────┐
│                        FFmpegRenderer                          │
│ build_zoompan_filter() → -vf zoompan=... → ffmpeg subprocess    │
└───────────────────────────┬──────────────────────────────────┘
                             ▼
                       scene-NNN.mp4 / final.mp4
                             │
                             ▼
                     MotionValidator (post-render QA)
```

===========================================================
## 3. MOTION PLANNER
===========================================================

A Motion Planner **exists**: `MotionPlanner` class, `src/video_core/cinematic/motion.py`.

**It is not AI-generated — there is no system prompt, no user prompt, and no LLM call.** Explicitly stating this per your instructions: *no LLM prompt exists for motion planning*. Below is the actual decision logic in full (already the complete implementation — not paraphrased):

**Source:** `src/video_core/cinematic/motion.py`

```python
@dataclass(frozen=True)
class MotionSpec:
    motion_type: str
    start_scale: float
    end_scale: float
    anchor_x: float
    anchor_y: float
    drift_x: float
    drift_y: float
    easing: str
    emotion: str

    def to_dict(self) -> dict:
        return asdict(self)


class MotionPlanner:
    def plan(
        self,
        scenes: list[dict],
        profile: str = "balanced",
        emotional_intensity: dict[int, str] | None = None,
    ) -> list[dict]:
        cfg = get_profile_config(profile)
        total = len(scenes)
        prev_motion_type = None
        repeat_count = 0

        for scene in scenes:
            scene_position = (scene["index"] - 1) / max(total - 1, 1) if total > 1 else 0.5
            scene_type = scene.get("scene_type", "generated_image")
            intensity = "normal"
            if emotional_intensity is not None:
                intensity = emotional_intensity.get(scene["index"], "normal")

            if scene_type in ("asset", "brand_card"):
                spec = _asset_motion(scene, cfg)
            else:
                spec = self._plan_generated(scene, scene_position, cfg, intensity)

            motion_type = spec.motion_type
            if prev_motion_type == motion_type:
                repeat_count += 1
            else:
                repeat_count = 1

            # brand_card must stay static — never swapped by variety override
            if repeat_count >= 3 and scene_type != "brand_card":
                # ... substitutes an alternative motion_type from the profile's
                # motion_map, cycling by scene index (full code in motion.py:289-320)
                ...

            scene["motion"] = spec.to_dict()
            prev_motion_type = spec.motion_type

        return scenes

    def _plan_generated(self, scene, scene_position, cfg, emotional_intensity="normal") -> MotionSpec:
        narration = scene.get("narration", "")
        emotion_profile = classify_scene(narration, scene_position)
        emotion_name = emotion_profile.emotion.value

        motion_type, scale_tier = cfg.motion_map.get(emotion_name, ("drift", "small"))

        if emotional_intensity == "peak":
            motion_type = "push_in_slow"
            scale_tier = "large"
        elif emotional_intensity == "emotional":
            scale_tier = "medium"
        elif emotional_intensity == "reflection":
            motion_type = "drift"
            scale_tier = "small"

        scene_duration = float(scene.get("duration_seconds", 5.0))
        start_s, end_s, ax, ay, dx, dy = _resolve_motion(
            motion_type, scale_tier, cfg, scene["index"], scene_duration
        )
        return MotionSpec(motion_type, round(start_s,4), round(end_s,4), ax, ay,
                           round(dx,4), round(dy,4), cfg.easing, emotion_name)
```

**"Output schema"** = the `MotionSpec` dataclass above, serialized as:

```json
{
  "motion_type": "push_in",
  "start_scale": 1.0,
  "end_scale": 1.234,
  "anchor_x": 0.5,
  "anchor_y": 0.5,
  "drift_x": 0.0,
  "drift_y": 0.0,
  "easing": "ease_in_out",
  "emotion": "curiosity"
}
```
This is a real, executed example — see Section 6 for the full input→output trace.

**Source file paths:**
- `src/video_core/cinematic/motion.py` — `MotionPlanner`, `MotionSpec`, `_resolve_motion`, `_asset_motion`
- `src/video_core/cinematic/profiles.py` — `motion_map` tables consumed by the planner
- `src/video_core/providers/tts/emotion.py` — `classify_scene` (shared emotion classifier)

===========================================================
## 4. MOTION PROMPT GENERATOR
===========================================================

**No Motion Prompt Generator exists.** There is no natural-language prompt of any kind for motion — `MotionSpec` fields are consumed directly as numeric inputs to an FFmpeg filter string builder (`build_zoompan_filter`), never as text handed to a generative model.

**"Prompt builder code"** — the closest analog is the pure-function filter builder, full source (`src/video_core/cinematic/ffmpeg_filters.py`):

```python
def _t_factor(total_frames: int, easing: str) -> str:
    inv_n = 1.0 / max(total_frames - 1, 1)
    t = f"(on)*{inv_n:.8f}"
    if easing == "ease_in_out":
        return f"({t})*({t})*(3-2*({t}))"
    return t


def build_zoompan_filter(width, height, fps, motion, duration_hint, supersample=1) -> str:
    motion_type = motion.get("motion_type", "static")
    start_scale = float(motion.get("start_scale", 1.0))
    end_scale = float(motion.get("end_scale", 1.0))
    anchor_x = float(motion.get("anchor_x", 0.5))
    anchor_y = float(motion.get("anchor_y", 0.5))
    easing = motion.get("easing", "linear")

    if motion_type == "static":
        return build_scale_crop_filter(width, height)

    if supersample > 1:
        sw, sh = width * supersample, height * supersample
        prefix, suffix = f"scale={sw}:{sh}:flags=lanczos,", f",scale={width}:{height}:flags=lanczos"
        out_w, out_h = sw, sh
    else:
        prefix, suffix, out_w, out_h = "", "", width, height

    total_frames = max(1, round(duration_hint * fps))
    t = _t_factor(total_frames, easing)

    dz = end_scale - start_scale
    z_expr = f"'{start_scale:.4f}+{dz:.6f}*({t})'"

    raw_dx, raw_dy = float(motion.get("drift_x", 0.0)), float(motion.get("drift_y", 0.0))

    def _clamp_drift(drift, anchor, start_zoom, end_zoom):
        if abs(drift) < 1e-9:
            return drift
        worst_zoom = min(start_zoom, end_zoom)
        x0 = anchor - 1.0 / (2.0 * worst_zoom)
        upper = 1.0 - 1.0 / worst_zoom
        room = min(upper - x0, x0)
        if abs(drift) > room and room > 1e-9:
            return room * (1.0 if drift > 0 else -1.0)
        return drift

    drift_x = _clamp_drift(raw_dx, anchor_x, start_scale, end_scale)
    drift_y = _clamp_drift(raw_dy, anchor_y, start_scale, end_scale)

    dx = f"+iw*{drift_x:.6f}*({t})" if abs(drift_x) > 1e-6 else ""
    dy = f"-ih*{drift_y:.6f}*({t})" if abs(drift_y) > 1e-6 else ""

    x_expr = f"'max(0,min(iw*{anchor_x:.4f}-iw/(2*zoom){dx},iw*zoom-{out_w}))'"
    y_expr = f"'max(0,min(ih*{anchor_y:.4f}-ih/(2*zoom){dy},ih*zoom-{out_h}))'"

    return f"{prefix}zoompan=z={z_expr}:x={x_expr}:y={y_expr}:d=1:s={out_w}x{out_h}:fps={fps}{suffix}"
```

**"Output schema"** = a raw FFmpeg `-vf` filter-graph string (not JSON), e.g. the real generated output shown in Section 6.

**How each camera parameter is decided — is it rule-based or AI-generated?**

**100% rule-based.** No parameter below is AI-generated:

| Parameter | How decided |
|---|---|
| Camera movement (which of 8 types) | Table lookup: `emotion → (motion_type, scale_tier)` per profile in `profiles.py` (`_STATIC_MAP`/`_BALANCED_MAP`/`_CINEMATIC_MAP`) |
| Motion direction | `drift_sign = 1.0 if scene_index % 2 == 0 else -1.0` — alternates by scene index parity, nothing else |
| Movement speed | Not modeled as an independent variable — implied by `(end_scale - start_scale) / duration` combined with easing curve |
| Zoom | `scale_range_{small,medium,large}` per profile, scaled by `duration_factor = scene_duration / reference_duration_seconds` (capped by `max_drift_scale_factor`) |
| Pan | `drift_amount` per profile × `duration_factor` × `drift_sign`, only for `motion_type == "drift"` |
| Dolly | Not a distinct concept — `push_in`/`pull_out` are dolly/zoom conflated into one scale parameter |
| Orbit | **Not implemented** — no orbit motion type exists anywhere in the code |
| Tilt | Only `tilt_up` exists (one direction, no `tilt_down`); moves `anchor_y` from 0.5→0.45 and adds `drift_y` |
| Crane | **Not implemented** |
| Handheld | **Not implemented** as a motion type. (`"handheld"` exists only in `images/shot_planner.py`'s `SHOT_TYPES` list — that's a *still-image framing descriptor* fed to the image generator, unrelated to camera movement during video) |
| Static | `motion_type == "static"` → `build_scale_crop_filter()`, a plain scale+crop with zero zoompan overhead |

**The full set of implemented `motion_type` values is exactly 8:** `static`, `push_in`, `push_in_slow`, `push_in_fast`, `pull_out`, `pull_out_wide`, `drift`, `tilt_up`. Anything else falls through to the `case _:` branch in `_resolve_motion` (logs a warning, falls back to `drift`).

**Source file paths:**
- `src/video_core/cinematic/ffmpeg_filters.py` — filter-string builder
- `src/video_core/cinematic/motion.py` — `_resolve_motion` (the actual per-type geometry table, reproduced in full in Section 3's file, not duplicated here)
- `src/ytfactory/video/ffmpeg.py` — `_vf_spatial` (thin wrapper calling `build_zoompan_filter`)

===========================================================
## 5. INPUTS AVAILABLE TO MOTION
===========================================================

Everything `MotionPlanner.plan()` receives is a `scene: dict` built from the Pydantic `Scene` model (`src/ytfactory/scenes/models.py`) **plus** enrichments added by earlier stages. Full schema, with **only the fields Motion actually reads bolded**:

```python
class Scene(BaseModel):
    model_config = ConfigDict(extra='allow')
    index: int
    title: str
    **narration: str**                       # ← fed to classify_scene()
    visual_prompt: str                      # NOT read by motion
    **duration_seconds: float**               # ← scales zoom/drift magnitude
    visual_metadata: VisualMetadata | None  # NOT read by motion
    **scene_type: str**                       # ← "asset"/"brand_card" branch vs generated
    shot_type: str                          # NOT read by motion (read by human_qa/image validators instead)
    pose: str | None                        # NOT read by motion
    composition: str | None                 # NOT read by motion
    motion_type: str | None                 # dead field — never set by scene planner, never read by MotionPlanner
    text_overlay: str | None                # NOT read by motion
    text_reveal_segments: list[str]         # NOT read by motion
    hold_required: bool                     # NOT read by motion
    **linked_segment: dict | None**           # ← only field: `.emotional_intensity` override
    **asset_path: str | None**                # ← only used by `_asset_motion()` for asset/brand_card scenes
    asset_id: str | None
    faithfulness_qa: dict | None
    scene_analysis: SceneAnalysis | None
    **animation: str | None**  # (dynamic key, not declared on model but read by `_asset_motion`)
```

`VisualMetadata` (`src/video_core/domain/visual_metadata.py`) — available on the scene but **not consumed by motion at all**:
```python
class VisualMetadata(BaseModel):
    era: Era | None                 # ANCIENT|HISTORICAL|MODERN|SYMBOLIC|TRANSITIONAL
    narrative_role: NarrativeRole | None   # STORY|ANALOGY|METAPHOR|EXPLANATION|ESTABLISHING|CTA
    environment: Environment | None        # FOREST|TEMPLE|ASHRAM|...|COSMIC
    mood: Mood | None                      # PEACEFUL|MYSTERIOUS|REVERENT|...
    visual_style: VisualStyle | None       # DOCUMENTARY|CINEMATIC|REALISTIC|...
    allow_modern_objects: bool
```

`linked_segment` (`src/ytfactory/retention/models.py::ScriptSegment`, serialized to dict) — only `emotional_intensity` is extracted, by `video_renderer_node`:
```python
class EmotionalIntensity(Enum):
    NORMAL = "normal"; EMOTIONAL = "emotional"; PEAK = "peak"; REFLECTION = "reflection"

@dataclass
class ScriptSegment:
    text: str
    start_time: float | None; end_time: float | None
    is_hook: bool; is_rehook: bool; is_frame_label: bool; is_bridge: bool
    resolves_story: bool
    emotional_intensity: EmotionalIntensity = EmotionalIntensity.NORMAL
```

**Summary — what's actually available vs. what's actually used:**

| Available to the scene dict | Used by Motion? |
|---|---|
| narration | ✅ (only signal driving emotion classification) |
| duration_seconds | ✅ (scales drift/zoom magnitude) |
| scene_type (asset/brand_card/generated_image) | ✅ (branches to `_asset_motion` vs `_plan_generated`) |
| linked_segment.emotional_intensity | ✅ (overrides motion_type/scale_tier when peak/emotional/reflection) |
| animation (legacy asset field) | ✅ (asset scenes only) |
| asset_path | ✅ (asset scenes only, indirectly via scene_type check) |
| scene index | ✅ (drift-direction alternation, rebalancer cycling) |
| script text as a whole | ❌ (only per-scene narration, no cross-scene context) |
| visual_prompt (image prompt) | ❌ |
| generated image itself (pixels) | ❌ (no vision analysis of the rendered image) |
| visual_metadata (era/mood/environment/style) | ❌ |
| shot_type (wide/close/handheld/drone/…) | ❌ |
| pose / composition | ❌ |
| symbolism / narrative_role | ❌ |
| storyboard metadata (STORYBOARD_HEADER prompt block) | ❌ (that governs image generation only) |

**Motion has no access to the image content, the image prompt, or any cinematography metadata chosen at image-generation time — it decides purely from narration text + duration + scene position + scene_type.**

===========================================================
## 6. MOTION OUTPUT
===========================================================

Full trace, **actually executed** against the real code (not fabricated):

**Input scene:**
```json
{
  "index": 1,
  "title": "The Silent Question",
  "narration": "What if everything you believed about the ancient temple was hidden from you? Beneath the surface lies a secret few have ever seen.",
  "duration_seconds": 6.5,
  "scene_type": "generated_image",
  "shot_type": "wide_shot",
  "visual_prompt": "ancient stone temple at dawn, mist rolling through carved pillars"
}
```

**↓ Motion planning** (`MotionPlanner().plan([scene], profile="cinematic")`)

`classify_scene(narration, position=0.0)`: sentence 1 ends in `?` → +2.0 curiosity; contains "what if" (+1.5), "beneath the surface" (+1.5 mystery), "hidden" (n/a), "secret" (+1.5 mystery); position < 0.2 → +1.0 curiosity arc bias. **Dominant = `curiosity`** (curiosity total 3.5 > mystery 3.0).

`_CINEMATIC_MAP["curiosity"] = ("push_in", "medium")`. `emotional_intensity` not supplied → stays `"normal"`, no override.

`_resolve_motion("push_in", "medium", cinematic_cfg, index=1, duration=6.5)`:
- `scale_range_medium = (1.0, 1.18)`, `reference_duration_seconds=5.0`, `max_drift_scale_factor=2.0`
- `duration_factor = min(6.5/5.0, 2.0) = 1.3`
- `hi = 1.0 + (1.18-1.0)*1.3 = 1.234`
- returns `(lo=1.0, hi=1.234, 0.5, 0.5, 0.0, 0.0)`

**↓ Generated motion object (`scene["motion"]`):**
```json
{
  "motion_type": "push_in",
  "start_scale": 1.0,
  "end_scale": 1.234,
  "anchor_x": 0.5,
  "anchor_y": 0.5,
  "drift_x": 0.0,
  "drift_y": 0.0,
  "easing": "ease_in_out",
  "emotion": "curiosity"
}
```
(`TransitionPlanner`/`EffectsPlanner` also ran on this scene in the same real test — full enriched scene dict shown for completeness):
```json
{
  "transition_in":  {"transition_type": "cross_dissolve", "duration_frames": 10, "color": "black", "from_emotion": "none", "to_emotion": "curiosity"},
  "transition_out": {"transition_type": "cross_dissolve", "duration_frames": 15, "color": "black", "from_emotion": "curiosity", "to_emotion": "none"},
  "effects": {"color_grade": "eq=contrast=1.06:saturation=1.12", "vignette": true, "film_grain": false, "blur_sigma": 0.0}
}
```

**↓ Final request sent to the "animation provider"** — there is no provider API call; this *is* the final artifact, an FFmpeg `-vf` string, passed to `subprocess.run(["ffmpeg", ...])` (1280×720, 30fps, supersample=2):

```
scale=2560:1440:flags=lanczos,zoompan=z='1.0000+0.234000*(((on)*0.00515464)*((on)*0.00515464)*(3-2*((on)*0.00515464)))':x='max(0,min(iw*0.5000-iw/(2*zoom),iw*zoom-2560))':y='max(0,min(ih*0.5000-ih/(2*zoom),ih*zoom-1440))':d=1:s=2560x1440:fps=30,scale=1280:720:flags=lanczos
```

Full `ffmpeg` invocation this feeds into (per `FFmpegRenderer.render()`, `src/ytfactory/video/ffmpeg.py`):
```
ffmpeg -y -loop 1 -framerate 30 -i scene-001.png -i scene-001.mp3
  -vf "<zoompan string above>,eq=contrast=1.06:saturation=1.12,vignette=angle=PI/5,
       fade=t=in:st=0:d=0.3333:color=black,fade=t=out:st=6.1667:d=0.5:color=black,subtitles='scene-001.srt'"
  -c:v libx264 -preset medium -crf 23 -pix_fmt yuv420p -profile:v high ... scene-001.mp4
```

===========================================================
## 7. MOTION QA
===========================================================

Exists as `MotionValidator` (category `motion`), `src/ytfactory/review/validation/rules/motion.py`. **No LLM/vision-based QA — rule-based checks + one classic-CV frame-diff detector.** Full evaluation criteria (6 rules):

| Rule | Severity | Checks |
|---|---|---|
| MOT_001 | high/medium | `duration_seconds` within `[motion_min_scene_duration_seconds=2.0, motion_max_scene_duration_seconds=120.0]` |
| MOT_002 | critical | `duration_seconds > 0` |
| MOT_003 | low | `shot_type` non-empty (inherited from Image Prompt Engine, not Motion Planner) |
| MOT_004 | low | `transition_in.transition_type` (or legacy `transition`) non-empty |
| MOT_005 | **critical, PipelineAbort** | No static shot >4s detected via frame-diff on the *rendered* `final.mp4` |
| MOT_006 | medium | Same `(motion_type, direction)` pair doesn't repeat ≥3 consecutive scenes |

**How bad motion is detected (MOT_005, the only real "motion quality" check on rendered pixels):**
```python
def _detect_static_shots(self, project_dir, context, threshold_seconds=4.0):
    final_video = Path(context.get("final_video_path", ""))
    if not final_video.is_file():
        return []
    import cv2
    subprocess.run(["ffmpeg", "-i", str(final_video), "-vf", "fps=2",
                    str(frames_dir / "frame_%05d.png")], capture_output=True, timeout=60)
    frame_paths = sorted(frames_dir.glob("frame_*.png"))
    prev_gray = None
    deltas = []
    for fp in frame_paths:
        img = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
        if prev_gray is not None:
            deltas.append(float(cv2.absdiff(prev_gray, img).mean()))
        prev_gray = img
    return _analyze_static_runs(deltas, threshold=2.0, frame_duration=0.5, threshold_seconds=4.0)


def _analyze_static_runs(deltas, threshold, frame_duration, threshold_seconds):
    """Flags continuous windows where mean grayscale delta stays < threshold
    for longer than threshold_seconds — i.e. the frame genuinely isn't moving,
    regardless of what MotionSpec claimed."""
    violations = []
    run_start = 0
    for i, d in enumerate(deltas):
        if d >= threshold:
            run_len = (i - run_start) * frame_duration
            if run_len > threshold_seconds:
                violations.append((run_start * frame_duration, i * frame_duration))
            run_start = i + 1
    run_len = (len(deltas) - run_start) * frame_duration
    if run_len > threshold_seconds:
        violations.append((run_start * frame_duration, len(deltas) * frame_duration))
    return violations
```
This samples the *actual encoded video* at 2fps, diffs consecutive grayscale frames, and flags any run where the frame genuinely didn't change for >4s — an empirical check independent of what `MotionSpec` claims. If OpenCV (`cv2`) isn't installed, the check silently returns `[]` (no violations reported — a fail-open behavior, not fail-closed).

MOT_006 direction/variety check:
```python
def _motion_direction(scene: dict) -> str:
    motion = scene.get("motion", {})
    mtype = motion.get("motion_type", "static")
    drift_x = float(motion.get("drift_x", 0.0))
    if mtype == "drift":   return "left" if drift_x > 0 else "right"
    if mtype == "push_in": return "in"
    if mtype == "pull_out":return "out"
    if mtype == "tilt_up": return "up"
    return "none"

def _check_motion_variety(scenes: list[dict]) -> list[str]:
    keys = [(s.get("motion", {}).get("motion_type", "static"), _motion_direction(s)) for s in scenes]
    # flags any (motion_type, direction) run of length >= 3
```

Downstream: `MotionRCAAnalyzer` (`review/rca/analyzers/motion.py`) maps each `MOT_00x` to a root cause + suggested fix; `MotionScorer` (`review/scoring/scorers/motion.py`) weights the category at `default_weight = 0.10` of total quality score with points `{MOT_002: 35, MOT_001: 30, MOT_004: 20, MOT_003: 15}`.

===========================================================
## 8. VIDEO PROVIDER
===========================================================

**There is no AI video-generation provider.** `video_core/providers/` only has `llm/`, `search/`, `image/`, `tts/`, `vision/` — no `video/` provider category exists anywhere in the provider factory system.

"Video generation" = a local **FFmpeg** binary invoked via `subprocess.run`, driven by two renderer entry points in `src/ytfactory/video/ffmpeg.py`:
- `FFmpegRenderer.render()` — per-scene MP4 (used for review/remediation, and as the sole path in the LangGraph flow)
- `FFmpegRenderer.render_continuous()` — single `filter_complex` pass for all scenes → one seamless `final.mp4` (no GOP boundary at scene cuts)

| Question | Answer |
|---|---|
| Which video provider | None (no cloud API) — local `ffmpeg` CLI |
| Which API | `subprocess.run(["ffmpeg", ...])` — no HTTP API |
| Duration | Per scene, `-t {duration_hint:.4f}` on the looped image input; `duration_hint` = narration audio length |
| Resolution | `Settings.video_width=1280`, `video_height=720` (720p, `16:9`) |
| Seed | N/A — motion is deterministic geometry, not stochastic generation; no seed concept exists in this stage (image *generation*, a separate earlier stage, has its own provider-level seed handling, out of scope here) |
| Camera controls | The `MotionSpec` fields themselves (`start_scale`/`end_scale`/`anchor_x/y`/`drift_x/y`/`easing`) — translated to FFmpeg `zoompan` parameters, not a provider API parameter |
| Prompt format | N/A — no prompt, an FFmpeg filter-graph string (see Section 4/6) |
| Encoder params | `-c:v libx264 -preset {Settings.video_preset="medium"} -crf {Settings.video_crf=23} -pix_fmt yuv420p -profile:v high`, `fps={Settings.video_fps=30}` |

===========================================================
## 9. FILES
===========================================================

```
src/video_core/cinematic/motion.py                          MotionPlanner, MotionSpec, emotion→geometry resolver (core motion logic)
src/video_core/cinematic/profiles.py                         RenderProfile enum, ProfileConfig, emotion→(motion_type,scale_tier) tables per profile
src/video_core/cinematic/rebalancer.py                        MotionRebalancer — post-pass that breaks long identical-motion runs
src/video_core/cinematic/transitions.py                       TransitionPlanner, TransitionSpec — emotion-pair-driven fade/cut selection
src/video_core/cinematic/effects.py                           EffectsPlanner, EffectSpec — color grade/vignette/grain/blur per emotion+profile
src/video_core/cinematic/config.py                            CinematicConfig — thin dataclass wrapping the profile name
src/video_core/cinematic/ffmpeg_filters.py                    build_zoompan_filter/build_scale_crop_filter — pure FFmpeg filter-string builders
src/video_core/providers/tts/emotion.py                       classify_scene — shared 12-emotion keyword classifier (drives both TTS prosody and motion)
src/ytfactory/video/ffmpeg.py                                 FFmpegRenderer — render()/render_continuous(), wires MotionSpec into actual ffmpeg calls
src/ytfactory/video/pipeline.py                                VideoPipeline — direct-call orchestration: Motion→Transition→Effects→Rebalance→render
src/ytfactory/agents/nodes/video_renderer.py                   video_renderer_node — LangGraph-path orchestration (same planner sequence)
src/ytfactory/scenes/models.py                                 Scene Pydantic model — duration_seconds/scene_type/narration/motion_type(dead field)
src/ytfactory/images/prompt_engine.py                          ImagePromptEngineV4 — assigns shot_type (consumed by MOT_003, not by MotionPlanner)
src/ytfactory/images/shot_planner.py                           plan_shots() — deterministic shot_type sequence (image framing, not camera movement)
src/ytfactory/retention/models.py                              ScriptSegment/EmotionalIntensity — source of the emotional_intensity override
src/ytfactory/review/validation/rules/motion.py                MotionValidator — MOT_001–006, static-shot frame-diff detector (Motion QA)
src/ytfactory/review/validation/config.py                      motion_min/max_scene_duration_seconds thresholds
src/ytfactory/review/rca/analyzers/motion.py                   MotionRCAAnalyzer — root-cause mapping for MOT_00x failures
src/ytfactory/review/scoring/scorers/motion.py                 MotionScorer — motion category weight (0.10) and per-rule point budget
src/ytfactory/config/settings.py                               render_profile, motion_supersample, video_width/height/fps/crf/preset
docs/video/CINEMATIC_MOTION_ENGINE_V1.md                       Original design spec — objective, philosophy, supported movements, future expansion
docs/video/MOTION_PLANNER_REUSABILITY_2026_07_13.md            Diagnostic confirming MotionPlanner/TransitionPlanner are shared, not duplicated, across both pipelines
docs/video/motion_variety_enhancement_spec.md                   Spec for the MotionRebalancer cooldown/variety pass
docs/video/fix_motion_interpolation_duration.md                 Fix-prompt: smoothness/duration-coverage investigation
docs/video/verify_motion_fix_and_pipeline_sweep.md              Verification of a state-persistence bug (scene-plan.json not re-saved with motion data)
docs/fix-prompts/kilo-fix-spec-opening-brandcard-motion.md      Fix-spec: opening-line leak / missing brand card / weak motion
```

===========================================================
## 10. DESIGN DECISIONS
===========================================================

**Why rule-based, not AI-generated:** `CINEMATIC_MOTION_ENGINE_V1.md`'s explicit objective was to upgrade the *renderer* from slideshow to cinematic **without touching** Scene Planner, Image Generation, TTS, or any other stage — i.e., motion was scoped as a pure rendering-layer enhancement, not a new AI subsystem. Reusing `classify_scene()` (already built for TTS prosody) instead of adding a second classifier was a deliberate no-duplication choice stated directly in `motion.py`'s docstring.

**Shared planner instances across both pipelines:** `MOTION_PLANNER_REUSABILITY_2026_07_13.md` explicitly checked for duplication risk (AS-002 audit flag) between `VideoPipeline` and `video_renderer_node` before allowing a third caller (`shorts_factory`) — confirmed `MotionPlanner`/`TransitionPlanner` are pure, stateless, dimension-agnostic, and safe to reuse rather than re-implementing.

**Strengths:**
- Fully deterministic — same scene plan + profile always produces the same motion (testable, no flakiness).
- Zero latency/cost — no model inference, no network calls; motion planning is sub-millisecond per scene.
- Emotion-motion coupling reuses an already-validated classifier, keeping TTS prosody and camera movement thematically consistent for free.
- Post-render empirical QA (MOT_005 frame-diff) catches *actual* static output regardless of what the planner claimed — a real safety net, not just self-reported metadata.
- Profile system (`draft/balanced/cinematic/premium`) cleanly separates quality/speed trade-off from the motion logic itself.

**Weaknesses:**
- Motion decisions are blind to the actual image content (composition, subject position, empty space) — a `push_in` on a portrait-orientation subject and a `push_in` on a wide landscape use identical anchor/scale math.
- Only 8 motion types, all zoom/pan/drift variants — no true crane, orbit, parallax, or rotation exists despite being listed as objectives in the original design doc.
- Emotion classification is keyword-based on narration text alone — no LLM or semantic understanding, so paraphrases without lexicon hits fall through to weak defaults (arc-position bias or `reflection`).
- Variety is enforced only by *repeat-count*, not by any richer notion of visual rhythm/pacing across the whole video.
- MOT_005's `cv2` import failure silently returns "no violations" rather than failing the check — a fail-open gap in the one empirical QA rule that inspects real pixels.

**Trade-offs accepted:** predictability and zero cost over per-scene visual sophistication; a shared, simple emotion signal over a dedicated (and more expensive) motion-intent classifier; profile-level tuning knobs over per-scene creative control.

===========================================================
## 11. KNOWN LIMITATIONS
===========================================================

(Confirmed directly from code/comments/specs — nothing invented.)

- Only 8 implemented motion types (`static`, `push_in`, `push_in_slow`, `push_in_fast`, `pull_out`, `pull_out_wide`, `drift`, `tilt_up`); no `tilt_down`, no orbit, no crane, no parallax, no rotation, no focus-pull, no depth zoom — despite these being listed in `CINEMATIC_MOTION_ENGINE_V1.md`'s "Supported Camera Movements" wishlist.
- Repetitive camera motion is possible and only corrected reactively: `MotionRebalancer` only intervenes once a run reaches `max_run_length=2` (i.e., 3rd+ consecutive repeat), and only substitutes within the same emotion's small acceptable-alternatives list (`_ACCEPTABLE_MOTIONS`, 2 alternatives per emotion).
- No continuity between scenes — each scene's motion is planned independently from its own narration/duration only; no shot-to-shot rhythm/pacing model exists across the full video.
- No visual callbacks — motion has zero awareness of recurring subjects, locations, or earlier scenes.
- Motion is blind to the actual generated image — no depth map, no segmentation, no object-aware anchoring; `anchor_x/y` defaults to frame-center (0.5, 0.5) for every motion type except `tilt_up` (0.45).
- Tier-2 motion types explicitly deferred in code: `motion.py`'s fallback-case comment states *"Tier 2 types (fog/dust/particles/light_rays) are deferred; add explicit case branches when assets are available."*
- Transitions use baked per-clip fades ("Strategy A"), not true overlapping cross-dissolves — `transitions.py` docstring: *"Strategy C (future, Phase 5): true overlapping cross-dissolves via a filter_complex graph. Requires re-encoding but enables genuine overlap."*
- `Scene.motion_type` field on the Pydantic model is dead code — declared with a description but never populated by the scene planner or read by `MotionPlanner`.
- MOT_005 (the only pixel-level motion QA check) fails open if `cv2`/OpenCV isn't installed — silently reports zero violations instead of failing the check.
- Emotion classification driving motion is keyword-lexicon based, not semantic — narration that expresses an emotion without matching keywords falls back to weak signals (scene-position arc bias, or the hardcoded default `reflection`).

===========================================================
## 12. FUTURE IMPROVEMENTS
===========================================================

(Only ideas already present in the codebase/docs — none invented for this review.)

From `docs/video/CINEMATIC_MOTION_ENGINE_V1.md` § **Future Expansion**, listed verbatim:
- AI depth maps
- Image segmentation
- Layered parallax
- Object-aware camera motion
- Dynamic lighting
- Particle effects
- Fog
- Rain
- Dust
- Volumetric light
- Cinematic lens effects

*(stated goal: support these "without redesigning the renderer")*

From `docs/video/CINEMATIC_MOTION_ENGINE_V1.md` § **Performance**:
- Premium profile may enable parallax, depth motion, and more advanced transitions.

From `src/video_core/cinematic/motion.py` (inline comment on the unrecognized-motion-type fallback):
- Tier 2 motion types — fog / dust / particles / light_rays — deferred until corresponding visual assets are available; add explicit `case` branches in `_resolve_motion` at that point.

From `src/video_core/cinematic/transitions.py` (module docstring, "Strategy C"):
- True overlapping cross-dissolves via a `filter_complex` graph (currently baked independent per-clip fades only) — described as a Phase 5 future strategy, requires re-encoding.
