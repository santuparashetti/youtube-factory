# SCENE_PLANNER_V2_SPEC.md

**Version:** v2.0  
**Status:** Ready for implementation  
**Target:** Kilo Code / Claude Code — direct repo access  
**Primary file:** `src/ytfactory/agents/nodes/scene_planner.py`  
**Touches:** models, prompts, settings, IMAGE_PROMPTS.md output  
**Do NOT touch:** TTS, subtitles, audio, Phase 2 rendering, composer, editorial_qa

---

## TOKEN EFFICIENCY

Read this spec fully before writing a single line. Implement all steps in one pass.
Do not re-read this file mid-implementation. Every section that says "PROMPT FILE CONTENT"
is the exact file content — write it verbatim, do not paraphrase. Sections marked
**[NO-CHANGE]** require no edits to that file.

---

## MOTIVATION (WHY THIS SPEC EXISTS)

Current scene_planner has four confirmed defects producing poor IMAGE_PROMPTS.md output:

1. **Style guide never injected** — hybrid cinematic style exists as a concept but appears
   in zero prompts. Every scene requests fully photorealistic characters, contradicting intent.
2. **No visual architecture** — scenes planned individually with no shared visual bible.
   19 scenes = 19 disconnected worlds. No environment recurs. No color arc. No shot progression.
3. **`_enforce_primary_kai_spec` too blunt** — prepends Kai descriptor to scenes with no
   character staging (scenes that describe an empty room, a cushion, a path), creating
   contradictions the image generator cannot resolve.
4. **Internal language leaked into user prompts** — "Storyboard Mode. The visual_prompt is
   the authoritative source..." is pipeline-internal text appearing in the IMAGE_PROMPTS.md
   prompts the user pastes into ChatGPT. Wastes tokens, confuses generator.

Additionally two open improvements from pipeline memory are implemented here:
- Structured prompt schema migration (flat `visual_prompt` → `StructuredImagePrompt`)
- Kai pose discipline (back/side/silhouette default; front-facing reserved for climax only)

---

## SCOPE BOUNDARY

**IN SCOPE (implement):**
- New `VisualBible` Pydantic model + generation step
- New `StructuredImagePrompt` Pydantic model (additive, backward compatible)
- New prompt files: `CINEMATIC_HYBRID_STYLE.md`, `VISUAL_BIBLE_PROMPT.md`, `KAI_POSE_RULES.md`
- New settings: `VISUAL_BIBLE_ENABLED`, `HYBRID_STYLE_ENABLED`, `KAI_POSE_DISCIPLINE_ENABLED`
- Fix `_enforce_primary_kai_spec` character staging check
- Fix Step 0 in `_write_prompts_file` (style + illustration instructions)
- Fix: remove "Storyboard Mode" language from compiled prompts
- Continuity validation pass (post-planning, flag-and-log only)

**OUT OF SCOPE (do not touch):**
- Composer, editorial_qa, TTS, WhisperX, subtitles
- Phase 2 rendering, motion, overlay compositing
- Camera-shake spec (separate spec)
- IMG_007/IMG_008 validators
- `_refine_prompt_from_score` (separate escalation)
- Any CLI changes
- Any test that currently passes and is unrelated to scene_planner

---

## STEP 1 — NEW SETTINGS

In `src/video_core/config/shared_settings.py`, add under the ANCHOR_CHARACTER block:

```python
# Scene Planner V2
VISUAL_BIBLE_ENABLED: bool = True
HYBRID_STYLE_ENABLED: bool = True
KAI_POSE_DISCIPLINE_ENABLED: bool = True
```

---

## STEP 2 — NEW PROMPT FILES

Create these three files exactly as written. Do not paraphrase.

### 2a. `src/ytfactory/prompts/CINEMATIC_HYBRID_STYLE.md`

```
HYBRID CINEMATIC STYLE (MANDATORY — apply to every scene):

ENVIRONMENT: 100% photorealistic. Architecture, interiors, nature, roads, sky, water,
furniture, props, lighting, shadows, reflections, textures — rendered as cinema
photography. Physically accurate lighting. Cinematic depth of field. Natural film grain.
High dynamic range. The environment must NEVER be painterly, illustrated, cartoon, or
stylized in any way.

HUMAN CHARACTERS ONLY: Premium hand-painted storybook illustration. Clean ink outlines.
Soft cel shading. Smooth painterly brush strokes. Slightly simplified anatomy. Expressive
faces. Rich color harmony. Graphic novel quality. Characters must NOT be photorealistic,
3D CGI, anime, Disney, Pixar, or watercolor.

COMPOSITING: Illustrated characters receive identical lighting as the photorealistic
environment. Characters cast realistic shadows. Match scene perspective, camera angle,
color temperature, and atmosphere. Final look: illustrated characters composited naturally
into a live-action cinematic world.
```

### 2b. `src/ytfactory/prompts/VISUAL_BIBLE_PROMPT.md`

```
You are a director of photography designing the visual architecture for a philosophical
documentary video. You are given the complete script. Your task is to produce a Visual
Story Bible BEFORE any individual scenes are planned.

Think cinematically. The video must feel like one coherent world, not a slideshow of
unrelated images. Design recurring environments, a color arc that mirrors the emotional
arc, and visual motifs that thread meaning through the whole piece.

Produce a JSON object with exactly these fields:

{
  "dominant_metaphor": "The single central visual image or metaphor that best embodies
    the video's core argument. One sentence.",
  "anchor_environments": [
    "Env 1: detailed photorealistic description — this environment recurs across scenes",
    "Env 2: ...",
    "Env 3: ..."
  ],
  "color_arc": {
    "opening": "palette description — typically cool, desaturated, wide depth of field",
    "build": "palette description — warming, tightening focal length",
    "climax": "palette description — most saturated or most stark, tightest frame",
    "resolution": "palette description — return toward opening palette but with one
      warm anchoring element"
  },
  "visual_motifs": [
    "Motif 1: a recurring symbolic object or spatial element",
    "Motif 2: ...",
    "Motif 3: ..."
  ],
  "shot_arc": {
    "opening_scenes": "establishing wide — place the viewer in the world",
    "build_scenes": "medium with depth — character and environment in dialogue",
    "climax_scene": "tight close-up or intimate medium — maximum emotional proximity",
    "resolution_scenes": "pull back to medium wide — earned distance, resolved energy"
  }
}

Output ONLY valid JSON. No preamble, no explanation, no markdown fences.
```

### 2c. `src/ytfactory/prompts/KAI_POSE_RULES.md`

```
KAI POSE DISCIPLINE (MANDATORY for all Kai-primary and Kai-spectator scenes):

DEFAULT POSES (use for all scenes except explicit climax):
- Back-facing: Kai seen from behind, facing away toward the environment
- Silhouette: Kai as a silhouette against a lit background
- Profile: Side view, 90 degrees, environment visible behind
- Over-shoulder: Camera behind Kai's shoulder looking at the scene

CLIMAX EXCEPTION (maximum ONE scene per video, emotional peak only):
- Partial front-facing: jaw line, side of face partially visible, partially obscured by
  shadow or depth of field blur

FORBIDDEN (never use — consistency risk across scenes):
- Full front-facing: face fully visible, looking directly at camera or viewer

CLOTHING CONSISTENCY:
- Kai's clothing must remain identical across all his appearances in one video unless
  the script explicitly depicts a change of scene or time.
- Describe Kai's clothing in full in scene 1. Subsequent scenes reference it by saying
  "same clothing as scene [N]" in the continuity_ref field.

PURPOSE:
- Back/side poses eliminate cross-scene face consistency failures
- The viewer projects themselves onto a character they cannot fully see — correct for
  philosophical content
- Illustrated style + consistent pose = stable visual identity without LoRA or character
  reference tools
```

---

## STEP 3 — NEW PYDANTIC MODELS

Locate the scene model file (likely `src/ytfactory/models/scene.py` or defined inside
`scene_planner.py`). Add these models. Do not remove or rename existing fields —
this is additive.

```python
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class VisualBible(BaseModel):
    """Visual architecture for the full video. Generated once before per-scene planning."""
    dominant_metaphor: str
    anchor_environments: list[str] = Field(min_length=2, max_length=4)
    color_arc: dict[str, str]  # keys: opening, build, climax, resolution
    visual_motifs: list[str] = Field(min_length=1, max_length=3)
    shot_arc: dict[str, str]  # keys: opening_scenes, build_scenes, climax_scene, resolution_scenes


class StructuredImagePrompt(BaseModel):
    """Per-scene structured prompt. Replaces flat visual_prompt string in generation."""

    shot_type: Literal[
        "establishing_wide",
        "medium",
        "close_up",
        "insert",
        "POV",
        "over_shoulder",
        "silhouette",
        "aerial",
    ]
    camera_angle: Literal[
        "eye_level",
        "low_angle",
        "high_angle",
        "dutch_tilt",
    ]
    environment_prompt: str
    """Photorealistic environment description only. No character details here."""

    character_staging: Optional[str] = None
    """Illustrated character description only. None if anchor_role == 'absent'."""

    lighting_match: str
    """How the character's lighting matches the environment. One sentence."""

    color_palette_phase: str
    """From visual_bible.color_arc — which phase this scene is in, plus specific palette."""

    continuity_ref: str
    """Link to prev/next scene. E.g. 'same environment as scene_003; Kai same clothing.'"""

    compiled_prompt: str
    """
    Final merged string for the image generator.
    Assembly order:
      1. HYBRID STYLE directive (from CINEMATIC_HYBRID_STYLE.md, compressed to ~100 tokens)
      2. Shot type and camera angle
      3. environment_prompt
      4. character_staging (if present) + lighting_match
      5. color_palette_phase
      6. continuity_ref
      7. KAI POSE DISCIPLINE reminder (if Kai scene)
      8. Negative suffixes: "no text, no watermark, no subtitle, no logo"
    """
```

---

## STEP 4 — VISUAL BIBLE GENERATION

In `scene_planner.py`, add method `_generate_visual_bible()` called ONCE at the start of
the planning phase, before the per-scene loop.

```python
def _generate_visual_bible(self, script_text: str) -> VisualBible:
    """
    Single LLM call. Reads full script. Returns VisualBible.
    If VISUAL_BIBLE_ENABLED is False, returns a minimal stub VisualBible
    with placeholder values so the rest of the pipeline still runs.
    """
    if not settings.VISUAL_BIBLE_ENABLED:
        return VisualBible(
            dominant_metaphor="A lone figure in a vast world",
            anchor_environments=["Interior space with natural light", "Outdoor landscape at golden hour"],
            color_arc={
                "opening": "cool desaturated grey-blue",
                "build": "warming amber tones",
                "climax": "deep gold, shallow depth of field",
                "resolution": "cool blue with one warm accent",
            },
            visual_motifs=["threshold/doorway", "open hands"],
            shot_arc={
                "opening_scenes": "establishing wide",
                "build_scenes": "medium with depth",
                "climax_scene": "tight close-up",
                "resolution_scenes": "medium wide",
            },
        )

    prompt_text = load_prompt("VISUAL_BIBLE_PROMPT.md")  # use existing prompt loader
    response = llm_call(
        system=prompt_text,
        user=script_text,
        temperature=0.4,  # lower temp — structural decisions, not creative writing
        model=settings.LLM_MODEL,
    )
    raw_json = response.strip()
    try:
        data = json.loads(raw_json)
        return VisualBible(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        logger.warning(f"VisualBible parse failed: {e} — using stub")
        # Fall back to stub rather than crashing
        return _stub_visual_bible()
```

Store the result on the scene plan:
- Add `visual_bible: Optional[VisualBible] = None` to the scene plan / plan output model
- Serialize to `scene-plan.json` under key `"visual_bible"`

---

## STEP 5 — PER-SCENE STRUCTURED PROMPT GENERATION

### 5a. New method `_build_structured_prompt()`

```python
def _build_structured_prompt(
    self,
    scene: Scene,
    visual_bible: VisualBible,
    scene_index: int,
    total_scenes: int,
    prev_scene: Optional[Scene] = None,
) -> StructuredImagePrompt:
    """
    Calls LLM once per scene to produce a StructuredImagePrompt.
    Injects visual_bible, style directive, and pose rules as context.
    """
    # Determine arc phase
    arc_phase = _get_arc_phase(scene_index, total_scenes)
    # arc_phase: "opening" | "build" | "climax" | "resolution"

    # Build context block for the LLM
    style_directive = load_prompt("CINEMATIC_HYBRID_STYLE.md")
    pose_rules = load_prompt("KAI_POSE_RULES.md") if scene.anchor_role != "absent" else ""
    kai_profile = load_prompt("KAI_PROFILE.md") if scene.anchor_role != "absent" else ""

    bible_context = f"""
VISUAL BIBLE (apply to this scene):
- Dominant metaphor: {visual_bible.dominant_metaphor}
- Anchor environments: {'; '.join(visual_bible.anchor_environments)}
- This scene's color phase ({arc_phase}): {visual_bible.color_arc.get(arc_phase, '')}
- Recommended shot type: {visual_bible.shot_arc.get(_arc_to_shot_key(arc_phase), '')}
- Visual motifs available: {', '.join(visual_bible.visual_motifs)}
"""

    prev_context = ""
    if prev_scene and prev_scene.structured_prompt:
        prev_context = f"""
PREVIOUS SCENE (scene {scene_index}):
- Environment: {prev_scene.structured_prompt.environment_prompt[:120]}
- Shot type: {prev_scene.structured_prompt.shot_type}
- Color palette: {prev_scene.structured_prompt.color_palette_phase[:80]}
Reference or contrast with this to maintain continuity.
"""

    system_prompt = f"""
You are a cinematographer writing image generation prompts for a philosophical documentary.

{style_directive}

{pose_rules}

{bible_context}

{prev_context}

SCENE POSITION: Scene {scene_index + 1} of {total_scenes}. Arc phase: {arc_phase}.

OUTPUT: Respond ONLY with a JSON object matching this schema exactly:
{{
  "shot_type": "<one of: establishing_wide|medium|close_up|insert|POV|over_shoulder|silhouette|aerial>",
  "camera_angle": "<one of: eye_level|low_angle|high_angle|dutch_tilt>",
  "environment_prompt": "<photorealistic environment description — no character details>",
  "character_staging": "<illustrated character description, or null if no character>",
  "lighting_match": "<one sentence: how character lighting matches environment>",
  "color_palette_phase": "<arc phase + specific palette for this scene>",
  "continuity_ref": "<reference to prev/next scene environment and Kai clothing if applicable>",
  "compiled_prompt": "<full merged prompt for image generator — see assembly rules below>"
}}

COMPILED_PROMPT ASSEMBLY RULES:
1. First line: HYBRID STYLE compressed directive (100 tokens max)
2. Shot type and camera angle
3. environment_prompt verbatim
4. If character_staging is not null: character_staging + lighting_match
5. color_palette_phase
6. continuity_ref (brief)
7. If Kai scene: one-line pose rule reminder
8. End with: "16:9 aspect ratio. No text, no watermark, no subtitle, no logo."

No preamble. No markdown fences. Output only valid JSON.
"""

    user_prompt = f"""
SCENE NARRATION:
{scene.narration_text}

KAI ROLE IN THIS SCENE: {scene.anchor_role}
{kai_profile if scene.anchor_role != 'absent' else ''}
"""

    response = llm_call(system=system_prompt, user=user_prompt, temperature=0.5)
    data = json.loads(response.strip())
    return StructuredImagePrompt(**data)
```

### 5b. Arc phase helpers

```python
def _get_arc_phase(scene_index: int, total_scenes: int) -> str:
    """Map scene position to emotional arc phase."""
    ratio = scene_index / max(total_scenes - 1, 1)
    if ratio < 0.20:
        return "opening"
    elif ratio < 0.65:
        return "build"
    elif ratio < 0.80:
        return "climax"
    else:
        return "resolution"


def _arc_to_shot_key(arc_phase: str) -> str:
    mapping = {
        "opening": "opening_scenes",
        "build": "build_scenes",
        "climax": "climax_scene",
        "resolution": "resolution_scenes",
    }
    return mapping.get(arc_phase, "build_scenes")
```

### 5c. Store on scene

After `_build_structured_prompt()` returns, set:
```python
scene.structured_prompt = structured_prompt
scene.visual_prompt = structured_prompt.compiled_prompt  # backward compat: keep visual_prompt populated
```

This ensures Phase 2 and any downstream that reads `visual_prompt` still works unchanged.

---

## STEP 6 — FIX `_enforce_primary_kai_spec`

Current behavior: blindly prepends Kai descriptor to any scene where `anchor_role == "primary"`.
Result: scenes with no character staging get contradictory prompts.

New behavior: check for character staging indicators first. If absent, reclassify to `"absent"`.

```python
# Character staging indicators — presence means a character is being staged in the scene
_CHARACTER_STAGING_INDICATORS = frozenset([
    "man", "woman", "figure", "person", "character", "human",
    "standing", "sitting", "walking", "facing", "looking", "holding",
    "leaning", "crouching", "gazing", "kneeling", "lying", "reaching",
    "kai", "instructor", "scholar", "villager", "elder",
])


def _has_character_staging(visual_prompt: str) -> bool:
    tokens = visual_prompt.lower().split()
    return any(indicator in tokens for indicator in _CHARACTER_STAGING_INDICATORS)


def _enforce_primary_kai_spec(self, scene: Scene) -> Scene:
    """
    If anchor_role is primary but no character staging is detected,
    reclassify to absent rather than prepending a contradictory descriptor.
    """
    if scene.anchor_role != "primary":
        return scene

    if not _has_character_staging(scene.visual_prompt or ""):
        logger.warning(
            f"Scene {scene.scene_id}: anchor_role=primary but no character staging detected. "
            f"Reclassifying to absent to avoid contradiction."
        )
        scene.anchor_role = "absent"
        return scene

    # Has character staging — original enforcement applies
    return _original_enforce_primary_kai_spec(scene)
```

Apply the same check to `_enforce_closing_scene_primary`.

---

## STEP 7 — FIX `_write_prompts_file` (IMAGE_PROMPTS.md output)

### 7a. Remove "Storyboard Mode" language

Search `_write_prompts_file` for all occurrences of:
```
Storyboard Mode. The visual_prompt is the authoritative source.
Do not invent people, animals, objects, actions, or environments not explicitly described.
Preserve intentional emptiness and negative space. If uncertain, omit rather than invent.
Match shot type, camera angle, composition, lighting, and environment exactly.
```

Delete this block entirely from the prompt output. It is internal documentation language,
not a valid image generator instruction. Each compiled_prompt already contains its own
style directive.

### 7b. Update Step 0 character brief

Replace the current Step 0 ChatGPT setup block with this:

```python
STEP_0_CHATGPT_TEMPLATE = """
**ChatGPT / DALL-E 3:** Paste this message ONCE at the start of a new conversation,
before pasting any scene prompt:

```
I am generating a {scene_count}-scene philosophical documentary storyboard in a specific
hybrid visual style. Keep this style consistent across every image.

VISUAL STYLE: The environment in every image must be 100% photorealistic — architecture,
nature, interiors, props, lighting, and shadows rendered as cinema photography. Human
characters only are illustrated — premium hand-painted storybook style with clean ink
outlines, soft cel shading, and graphic novel quality. Characters are composited into the
photorealistic environment with matching lighting and realistic shadows.

ANCHOR CHARACTER (KAI): Appears in scenes {primary_scene_list}. Kai is a young man,
late 20s, lean build, short dark hair, simple clothing. Render Kai as an illustrated
storybook character (NOT photorealistic) — ink outlines, cel shading, painterly texture.
Kai is almost always shown from behind, in silhouette, or in profile — almost never
full front-facing.

Keep Kai's illustrated appearance identical across all his scenes. I will paste each
scene prompt one by one now.
```

Keep all {scene_count} generations in ONE conversation window. If style drifts, paste
scene 1 back and say "same hybrid style — continue with scene [X]".

**Midjourney / Leonardo:** Generate scene 1 first. Use that as your style reference
(--sref) for all subsequent scenes. For Kai-primary scenes, also use --cref.
"""
```

### 7c. Update the per-scene prompt block

Replace the current prompt rendering block (which wraps in `> blockquote` with the
storyboard language) with:

```python
def _render_scene_prompt_block(scene: Scene) -> str:
    prompt_text = (
        scene.structured_prompt.compiled_prompt
        if scene.structured_prompt
        else scene.visual_prompt
    )
    return f"**Image Prompt:**\n\n{prompt_text}\n"
```

No blockquote wrapper. No "Storyboard Mode." The compiled_prompt is self-contained.

---

## STEP 8 — CONTINUITY VALIDATION PASS

Add method `_validate_visual_continuity()` called after all scenes are planned.
This is **flag-and-log only** — it never blocks the pipeline.

```python
def _validate_visual_continuity(
    self,
    scenes: list[Scene],
    visual_bible: VisualBible,
) -> list[str]:
    """
    Post-planning validation. Returns list of warning strings.
    Logs all warnings. Does not raise or block.
    """
    warnings = []
    scene_count = len(scenes)

    # Check 1: Anchor environment reuse
    anchor_refs = 0
    for scene in scenes:
        if scene.structured_prompt:
            env = scene.structured_prompt.environment_prompt.lower()
            for anchor in visual_bible.anchor_environments:
                # Simple substring match on first 30 chars of anchor description
                key_words = anchor.lower().split()[:4]
                if any(w in env for w in key_words):
                    anchor_refs += 1
                    break
    if anchor_refs < max(2, scene_count // 5):
        warnings.append(
            f"CONTINUITY: Anchor environments appear in only {anchor_refs}/{scene_count} scenes. "
            f"Target ≥{max(2, scene_count // 5)} for visual coherence."
        )

    # Check 2: Shot type variety
    shot_types = [
        s.structured_prompt.shot_type
        for s in scenes
        if s.structured_prompt
    ]
    if shot_types:
        most_common = max(set(shot_types), key=shot_types.count)
        most_common_ratio = shot_types.count(most_common) / len(shot_types)
        if most_common_ratio > 0.60:
            warnings.append(
                f"CONTINUITY: '{most_common}' used in {shot_types.count(most_common)}/{len(shot_types)} scenes "
                f"({most_common_ratio:.0%}). Recommend diversifying shot types."
            )

    # Check 3: Climax scene has tight shot
    climax_index = int(scene_count * 0.70)
    climax_scene = scenes[climax_index] if climax_index < scene_count else None
    if climax_scene and climax_scene.structured_prompt:
        if climax_scene.structured_prompt.shot_type not in ("close_up", "insert", "medium"):
            warnings.append(
                f"CONTINUITY: Scene {climax_index + 1} (climax position) has shot_type "
                f"'{climax_scene.structured_prompt.shot_type}'. Expected close_up or medium for emotional peak."
            )

    # Check 4: Kai front-facing overuse
    front_facing_count = 0
    for scene in scenes:
        if scene.structured_prompt and scene.anchor_role == "primary":
            staging = (scene.structured_prompt.character_staging or "").lower()
            if "facing forward" in staging or "front-facing" in staging or "looking directly" in staging:
                front_facing_count += 1
    if front_facing_count > 1:
        warnings.append(
            f"CONTINUITY: Kai is front-facing in {front_facing_count} scenes. "
            f"Pose discipline allows maximum 1 (climax only)."
        )

    for w in warnings:
        logger.warning(w)

    return warnings
```

Store warnings in `scene-plan.json` under `"continuity_warnings"` for inspection.

---

## STEP 9 — INTEGRATION: WIRE INTO SCENE PLANNING FLOW

In the main scene planning entry point (the method that orchestrates scene planning),
add these calls in this order:

```python
# 1. Generate visual bible (once, before per-scene loop)
visual_bible = self._generate_visual_bible(script_text=full_script_text)
plan.visual_bible = visual_bible

# 2. Per-scene loop (existing loop, add structured prompt generation)
for i, scene in enumerate(plan.scenes):
    prev = plan.scenes[i - 1] if i > 0 else None
    scene.structured_prompt = self._build_structured_prompt(
        scene=scene,
        visual_bible=visual_bible,
        scene_index=i,
        total_scenes=len(plan.scenes),
        prev_scene=prev,
    )
    scene.visual_prompt = scene.structured_prompt.compiled_prompt  # backward compat

# 3. Kai spec enforcement (existing call — now with staging check from Step 6)
for scene in plan.scenes:
    scene = self._enforce_primary_kai_spec(scene)

# 4. Continuity validation (after all scenes planned)
continuity_warnings = self._validate_visual_continuity(plan.scenes, visual_bible)
plan.continuity_warnings = continuity_warnings

# 5. Write IMAGE_PROMPTS.md (existing call — now uses structured prompts via Step 7)
self._write_prompts_file(plan)
```

---

## STEP 10 — SCENE MODEL ADDITIONS

Add these fields to the Scene model (additive, all Optional with defaults):

```python
structured_prompt: Optional[StructuredImagePrompt] = None
```

Add these fields to the plan/output model:

```python
visual_bible: Optional[VisualBible] = None
continuity_warnings: list[str] = Field(default_factory=list)
```

Ensure `scene-plan.json` serializes both. Use `.model_dump()` — Pydantic v2 standard.

---

## STEP 11 — GUARD: HYBRID STYLE DISABLED PATH

If `HYBRID_STYLE_ENABLED = False`, the `_build_structured_prompt()` method should:
- Still produce a `StructuredImagePrompt`
- Omit the style directive block from `compiled_prompt`
- Use the narration + visual bible context only

This lets the pipeline fall back to plain documentary prompts if the hybrid style is
toggled off, without breaking the structured schema.

---

## TEST COVERAGE

Add to `tests/test_scene_planner.py`:

1. `test_visual_bible_generation_stub()` — when VISUAL_BIBLE_ENABLED=False, stub returns valid VisualBible
2. `test_visual_bible_json_parse()` — valid JSON from LLM parses to VisualBible correctly
3. `test_visual_bible_json_parse_failure_returns_stub()` — invalid JSON falls back to stub, no crash
4. `test_structured_prompt_fields_present()` — all 8 fields populated on returned StructuredImagePrompt
5. `test_compiled_prompt_contains_style_directive()` — "HYBRID CINEMATIC STYLE" in compiled_prompt when HYBRID_STYLE_ENABLED=True
6. `test_compiled_prompt_no_storyboard_mode_language()` — "Storyboard Mode" NOT in any compiled_prompt
7. `test_enforce_primary_kai_spec_no_staging_reclassifies_to_absent()` — scene with anchor_role=primary and no staging indicators → reclassified to absent
8. `test_enforce_primary_kai_spec_with_staging_preserved()` — scene with staging indicators → stays primary
9. `test_continuity_validation_shot_variety_warning()` — all medium shots → warning emitted
10. `test_continuity_validation_kai_front_facing_warning()` — 2 front-facing Kai scenes → warning emitted
11. `test_visual_prompt_backward_compat()` — scene.visual_prompt == scene.structured_prompt.compiled_prompt

Run full suite after implementation. Target: all existing 3185+ tests pass. No regressions.

---

## KNOWN AMBIGUITIES (resolve these before implementing)

1. **Prompt loader function name** — confirm the exact function used to load `.md` files
   from `src/ytfactory/prompts/`. Likely `load_prompt()` or similar. Match existing pattern
   from KAI_PROFILE.md loading.

2. **LLM call signature** — confirm the exact method signature for making an LLM call
   inside scene_planner.py (temperature param, model param, return type). Match existing calls.

3. **Scene plan output model location** — confirm whether `VisualBible` and
   `continuity_warnings` go on a `ScenePlan` model or directly on the dict written to
   `scene-plan.json`. Match existing pattern.

4. **`_write_prompts_file` trigger guard** — existing code skips this on `plan-scenes`
   command (routes through ScenePipeline). Ensure the new Visual Bible generation also
   respects this guard — visual bible generation should be skipped on the same path.

---

## DO NOT IMPLEMENT

- Do not add any new CLI commands or menu options
- Do not modify Phase 2 in any way
- Do not add image scoring or quality gate changes
- Do not change the LLM model or provider
- Do not implement the PHASE 2 editorial QA auto-fixer (separate, gated on ledger data)
- Do not implement `build_recompose_directive` (dormant, unwired)
- Do not remove or rename `visual_prompt` — keep it populated for backward compat

---

*End of SCENE_PLANNER_V2_SPEC.md*
