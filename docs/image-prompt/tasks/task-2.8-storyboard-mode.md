# Task 2.8 — STORYBOARD MODE + STRICT SCENE FIDELITY
**File:** `src/ytfactory/agents/prompts/scene_planner.py`
**Type:** Prompt template change only — no logic, no new LLM calls, no new settings
**Baseline:** 2820 tests passing

---

## Token Efficiency

- No new LLM calls
- No new models, no new settings, no new API calls
- Template addition only — ~100 tokens added per generation call
- Net cost: zero additional API calls

---

## Change — Two Locations (Option C)

### Location 1 — Upstream: generation prompt template
In the visual prompt generation template, prepend the two blocks below
**before all existing content**. These must be the first thing the
generation model reads — position 0 in the template string.
This shapes how DeepSeek V3.2 writes each scene's visual_prompt.

### Location 2 — Downstream: IMAGE_PROMPTS.md and manifest output
The same STORYBOARD MODE condensed header must be prepended to every
`visual_prompt` string written into:
- `image_prompts_manifest.json` → each scene's `"visual_prompt"` field
- `IMAGE_PROMPTS.md` → each scene's image prompt block

This is the file the user copies from when manually generating images
on web tools (Leonardo, Midjourney, etc.). The storyboard instruction
must be present in those files so the web image generator receives it
directly.

Find where these output files are written — likely
`src/ytfactory/images/prompt_engine.py` or the scene assets export step
in `src/ytfactory/agents/nodes/scene_assets.py` — and prepend this
condensed header to each visual_prompt before writing:

```python
STORYBOARD_HEADER = (
    "Storyboard Mode. "
    "The visual_prompt is the authoritative source. "
    "Do not invent people, animals, objects, actions, or environments "
    "not explicitly described. "
    "Preserve intentional emptiness and negative space. "
    "If uncertain, omit rather than invent. "
    "Match shot type, camera angle, composition, lighting, and "
    "environment exactly.\n\n"
)

def prepend_storyboard_header(visual_prompt: str) -> str:
    """Prepend storyboard header to final output prompt."""
    if visual_prompt.startswith("Storyboard Mode"):
        return visual_prompt  # already prepended, idempotent
    return STORYBOARD_HEADER + visual_prompt
```

Apply `prepend_storyboard_header()` to every scene's visual_prompt
at the point of writing to the manifest and IMAGE_PROMPTS.md.
Do NOT apply to brand_card scenes — they have no meaningful visual_prompt.

Brand card scene guard:
```python
if scene.get("scene_type") != "brand_card":
    visual_prompt = prepend_storyboard_header(visual_prompt)
```

**Block 1 — STORYBOARD MODE:**
```
STORYBOARD MODE

Generate only what is explicitly visible in the visual_prompt.
The visual_prompt is the authoritative source.
The narration provides emotional context only.
Do NOT invent people, animals, objects, actions, or environments not explicitly described.
Preserve intentional emptiness and negative space.
If uncertain, omit rather than invent.
Match the requested shot type, camera angle, composition, lighting, and environment exactly.
```

**Block 2 — STRICT SCENE FIDELITY:**
```
STRICT SCENE FIDELITY

- The visual_prompt is the single source of truth.
- Narration influences only mood and storytelling intent, never the visible subjects.
- Never invent characters, animals, props, architecture, or actions.
- Never continue subjects from previous scenes unless explicitly requested.
- Preserve intentional emptiness and negative space.
- When uncertain, omit rather than invent.
- Match the requested camera angle, composition, lighting, and scale exactly.
- Treat every scene as an independent storyboard frame, not an artistic reinterpretation.
- Verify that the generated image matches the visual_prompt before considering the scene complete.
```

---

## Required Template Order After This Change

Every visual prompt generation call must follow this exact order:

```
[STORYBOARD MODE]
[STRICT SCENE FIDELITY]
[REQUIRED VISUAL: {visual_anchor}]          ← Task 2.7 narration anchor
[NARRATION: {narration}]                    ← Task 2.7 narration context
[CONSTRAINT: entity/human classification]   ← Task 2.5 user-turn injection
[REQUIRED SETTING: {environment}]           ← Task 2.5 environment constraint
[FORBIDDEN WORDS list]                      ← Task 2.4 forbidden words
[camera/shot rules]
[era/mood/style]
→ generate visual_prompt
```

The Task 2.7 narration anchor block is kept exactly as implemented —
only its position changes: it now follows the two new blocks instead of
leading the template.

---

## Tests

```python
def test_storyboard_mode_first_in_template():
    from ytfactory.agents.prompts import scene_planner as sp
    assert sp.VISUAL_PROMPT_TEMPLATE.strip().startswith("STORYBOARD MODE")

def test_strict_fidelity_before_narration_anchor():
    from ytfactory.agents.prompts import scene_planner as sp
    storyboard_pos = sp.VISUAL_PROMPT_TEMPLATE.index("STORYBOARD MODE")
    fidelity_pos = sp.VISUAL_PROMPT_TEMPLATE.index("STRICT SCENE FIDELITY")
    anchor_pos = sp.VISUAL_PROMPT_TEMPLATE.index("REQUIRED VISUAL")
    assert storyboard_pos < fidelity_pos < anchor_pos

def test_omit_rather_than_invent_present():
    from ytfactory.agents.prompts import scene_planner as sp
    assert "omit rather than invent" in sp.VISUAL_PROMPT_TEMPLATE

def test_independent_storyboard_frame_present():
    from ytfactory.agents.prompts import scene_planner as sp
    assert "independent storyboard frame" in sp.VISUAL_PROMPT_TEMPLATE

def test_single_source_of_truth_present():
    from ytfactory.agents.prompts import scene_planner as sp
    assert "single source of truth" in sp.VISUAL_PROMPT_TEMPLATE

def test_narration_context_only_present():
    from ytfactory.agents.prompts import scene_planner as sp
    assert "emotional context only" in sp.VISUAL_PROMPT_TEMPLATE

# Downstream output tests
def test_storyboard_header_in_manifest():
    # Every non-brand-card scene in image_prompts_manifest.json
    # must have visual_prompt starting with "Storyboard Mode"
    manifest = load_manifest(project_id)
    for scene in manifest["scenes"]:
        if scene.get("scene_type") == "brand_card":
            continue
        assert scene["visual_prompt"].startswith("Storyboard Mode"), \
            f"Scene {scene['index']} missing storyboard header"

def test_storyboard_header_in_image_prompts_md():
    # IMAGE_PROMPTS.md must contain "Storyboard Mode" for each scene block
    content = Path("IMAGE_PROMPTS.md").read_text()
    assert content.count("Storyboard Mode") >= 29  # 30 scenes - 1 brand card

def test_prepend_storyboard_header_idempotent():
    prompt = "Storyboard Mode. Already has header. Some scene content."
    result = prepend_storyboard_header(prompt)
    assert result.count("Storyboard Mode") == 1

def test_brand_card_excluded_from_header():
    scene = {"scene_type": "brand_card", "visual_prompt": "Brand Card prompt"}
    result = apply_storyboard_to_scene(scene)
    assert not result["visual_prompt"].startswith("Storyboard Mode")
```

---

## Do NOT change

- Any logic in `scene_planner.py` (nodes)
- `validators.py`
- Entity extraction
- Retry loop
- Task 2.7 narration anchor block content — keep it, just ensure it
  comes after the two new blocks
- Task 2.6 LLM validation
- Any other prompt template (script enhancer, subtitle editor, etc.)
- Test baseline: 2820 passing — do not regress
