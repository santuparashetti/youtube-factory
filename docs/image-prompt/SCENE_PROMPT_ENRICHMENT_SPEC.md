# SCENE PROMPT ENRICHMENT — SPEC

**Status:** Ready for implementation  
**Scope:** Scene planner — four additions to prompt generation and post-processing  
**Touches:** `src/ytfactory/agents/nodes/scene_planner.py` (scene model + system
prompt + post-processing), `src/ytfactory/cli.py` (probe command update),
`tests/test_scene_planner.py`  
**Depends on:** KAI_ANCHOR_CHARACTER_SPEC (implemented), AUDIENCE_VISUAL_DIRECTIVE
(implemented)  
**Token budget:** Medium — three new post-processing functions + system prompt
additions + two new scene model fields  

---

## WHY

First real Phase 1 run exposed two scene prompt failures:

**Failure 1 — Secondary characters have no appearance standard**
The scene planner prompt only has rules for Kai. Every other character
(instructor, executives, scholar, villager) is described by role only —
appearance, ethnicity, clothing, and position are left to the image generator.
Result: generator defaults to South Asian / ambiguous faces and random clothing,
violating the Western audience directive and breaking cross-scene character
consistency.

**Failure 2 — No story beat / environment continuity**
The scene planner generates each `visual_prompt` in complete isolation. It does
not know that scene 5 and scene 6 are the same story moment in the same location.
Result: consecutive scenes in the same narrative beat get different environments
(outdoor park → indoor hall), breaking visual continuity.

Both failures require source-level fixes in the scene planner. Manual prompt
corrections are not the answer.

---

## SOLUTION OVERVIEW

```
SCENE PLANNER LLM OUTPUT
        |
        ├─ scene_group_id      ← new field: tags scenes in same story beat
        ├─ environment_anchor  ← new field: canonical env desc for the group
        |
        ▼
POST-PROCESSING CHAIN (after LLM parse, before return)
        |
        ├─ [existing] _enforce_primary_kai_spec
        ├─ [existing] _enforce_closing_scene_primary
        ├─ [NEW]      _propagate_environment_anchors   ← Fix 2: env continuity
        ├─ [NEW]      _enforce_style_footer            ← Fix 3: quality footer
        └─ return scenes

SCENE PLANNER SYSTEM PROMPT additions:
        ├─ CHARACTER COMPLETENESS RULE         ← Fix 1A: per-scene character spec
        ├─ CROSS-SCENE CHARACTER LOCKING RULE  ← Fix 1B: consistency across group
        └─ SCENE CONTINUITY RULE               ← Fix 2: story beat grouping

PROBE COMMAND:
        └─ Scene group reporting added         ← Fix 4
```

---

## FIX 1 — CHARACTER COMPLETENESS RULE

### 1A — Scene planner system prompt addition

Find the scene planner's system prompt (inline Python or companion .md).
Add this section immediately after the KAI ANCHOR CHARACTER section:

```
---

## CHARACTER COMPLETENESS RULE (applies to ALL scenes)

Every human character visually present in a scene MUST be explicitly described
in the visual_prompt. Do not leave any character's appearance to the image
generator's assumption — generators will default to whatever is convenient,
which destroys cross-scene consistency.

For EVERY non-Kai character in the scene, specify all five of:

1. ROLE       — what they are in this scene (e.g. instructor, executive,
                scholar, villager, child)
2. APPEARANCE — age range, build, skin tone, hair. Default: Western European
                (light to medium complexion, Western hair and features) UNLESS
                the script explicitly names a cultural identity for this
                character (e.g. "a Japanese elder", "an African-American CEO")
3. CLOTHING   — specific garment, color, style
                (e.g. "simple grey linen shirt, dark trousers"
                      "formal dark navy business suit, white shirt, slim tie")
4. POSITION   — where in the frame relative to the composition
                (e.g. "centre-left", "background right", "foreground")
5. ACTION     — what they are doing in this exact moment
                (e.g. "extending a payment envelope", "standing at attention",
                       "turning to walk away")

For GROUP characters (e.g. a group of executives), describe the GROUP as a unit:
  - Number: approximate count ("8 to 10 executives")
  - Shared appearance: "Western European appearance, late 40s to 60s"
  - Shared clothing: "formal dark business suits"
  - Formation: "standing in neat rows"
  - Expression/action: "strained forced smiles"

Kai's appearance is locked via KAI_COMPRESSED_SPEC — if his spec is already
in the prompt, do NOT re-describe him here. Just add the secondary characters.

NEVER write: "a man in a suit", "some executives", "an instructor"
ALWAYS write: "a man in his 50s, Western European, silver hair, simple grey
linen shirt and dark trousers, standing centre-left, turning to walk away"
```

### 1B — No code changes required for Fix 1A
The LLM enforces this rule at generation time via the prompt addition. The
existing `_enforce_primary_kai_spec` guard handles Kai separately. No new
post-processing function needed for character completeness — this is a prompt
instruction, not a mechanical transformation.

### 1C — Cross-scene secondary character locking (prompt addition)

**The gap:** CHARACTER COMPLETENESS RULE describes each character per-scene,
but the LLM may describe the same instructor differently in scene 5 vs scene 6
— different clothing, different age, different appearance. Within a scene group,
secondary character descriptions must be locked to the first scene's version.

Add this sub-rule inside the CHARACTER COMPLETENESS RULE block in the system
prompt, immediately after the GROUP characters paragraph:

```
## CROSS-SCENE CHARACTER LOCKING (within a scene_group)

If this scene is part of a scene_group (scene_group_id is not null) AND it is
NOT the first scene in the group:

  For every secondary character who appeared in the first scene of this group,
  do NOT re-invent their description. Instead:
  1. Reference them explicitly: "same instructor as in scene [first_scene_id]"
  2. Repeat ONLY their key locking descriptors (role + clothing key item):
     "same instructor as in scene 5 — grey linen shirt, dark trousers"
  3. Then describe only what CHANGES for this character in this scene
     (their new action, position, expression).

This ensures the image generator receives a consistent character description
and does not re-invent the character's appearance between scenes.

EXAMPLE (scene 6, same group as scene 5):
  WRONG:  "An instructor in a grey coat collects payment..."
  CORRECT: "Same instructor as in scene 5 — grey linen shirt, dark trousers —
            now turning to walk away, holding a small payment envelope."
```

---

## FIX 2 — SCENE CONTINUITY (STORY BEAT GROUPING)

### 2A — Scene model: two new fields

In the per-scene Pydantic model, add:

```python
scene_group_id: str | None = None
# Identifies scenes that are part of the same story beat (same location,
# same time, continuous action). Scenes with the same non-None value are
# grouped. Example: "laughing_club_park", "gallery_transaction", "home_dawn"
# Set by the LLM; propagated in post-processing.

environment_anchor: str | None = None
# The canonical environment description for this scene group.
# Set by the LLM for the FIRST scene in each group.
# Subsequent scenes in the group get this injected by _propagate_environment_anchors.
```

### 2B — Scene planner system prompt addition

Add this section immediately after the CHARACTER COMPLETENESS RULE:

```
---

## SCENE CONTINUITY RULE

Before writing visual_prompts, identify SCENE GROUPS — consecutive scenes
that are part of the same story moment (same physical location, same time
of day, continuous or directly sequential action).

For each group:
  1. Assign a short descriptive scene_group_id to all scenes in the group
     (e.g. "laughing_club_park", "gallery_sale", "home_dawn_sequence")
     Use snake_case, max 4 words, descriptive of the location/moment.
     Scenes NOT part of any group: leave scene_group_id as null.

  2. For the FIRST scene in the group:
     - Write a full, detailed environment_anchor — the canonical description
       of this location: what type of space, time of day, lighting quality,
       color palette, key environmental elements.
     - This anchor is the CONTRACT that all subsequent scenes in the group
       must match exactly.
     Example environment_anchor:
     "Manicured urban park at pre-dawn. Cool flat blue light with first
      hints of golden hour on the skyline. City skyscrapers visible in
      morning haze behind. Dew on grass. Color palette: slate grey, muted
      navy, faint cold amber."

  3. For SUBSEQUENT scenes in the same group:
     - Open the visual_prompt with: "Continuous from scene [first_scene_id].
       [environment_anchor short form repeated verbatim]."
     - Only describe what CHANGES: character positions, actions, emotional
       state, specific focal point.
     - Do NOT re-describe the environment from scratch — reference the anchor.
     - The environment_anchor field for non-first scenes: copy the same value
       as the first scene in the group (for post-processing reference).

EXAMPLE — scenes 5 and 6 are both at the laughing club in the park:

Scene 5 (first in group):
  scene_group_id: "laughing_club_park"
  environment_anchor: "Manicured urban park at pre-dawn. Cool flat blue light
    with first hints of golden hour catching the city skyline. Skyscrapers
    in soft morning haze. Dew on grass. Slate grey, muted navy, cold amber."
  visual_prompt: "[full scene 5 description with environment included]"

Scene 6 (subsequent in same group):
  scene_group_id: "laughing_club_park"
  environment_anchor: "Manicured urban park at pre-dawn. Cool flat blue light
    with first hints of golden hour catching the city skyline. Skyscrapers
    in soft morning haze. Dew on grass. Slate grey, muted navy, cold amber."
  visual_prompt: "Continuous from scene 5. Manicured urban park, pre-dawn,
    cool blue light, city skyline in haze. [then: what changed — the payment
    transaction, characters' updated positions and actions]"
```

### 2C — Post-processing: `_propagate_environment_anchors`

Add this function and wire it into the post-processing chain.

This is the deterministic safety net — if the LLM correctly follows the
continuity rule in its prompts, this function makes no visible change. If
the LLM forgets to open a subsequent scene with the environment anchor, this
function injects it automatically.

```python
def _propagate_environment_anchors(scenes: list[dict]) -> list[dict]:
    """
    For scenes in the same scene_group, ensure the environment anchor from
    the first scene is referenced in all subsequent scenes in the group.

    If a subsequent scene's visual_prompt already opens with "Continuous from
    scene [N]", it is left unchanged (LLM followed the rule).

    If it does not, the anchor is prepended: "Continuous from scene [N].
    [environment_anchor]. [original prompt]"
    """
    # Build group registry: group_id -> (first_scene_id, environment_anchor)
    group_registry: dict[str, tuple[int, str]] = {}

    for scene in scenes:
        group_id = scene.get("scene_group_id")
        if not group_id:
            continue

        scene_id = scene["scene_id"]
        env_anchor = scene.get("environment_anchor") or ""

        if group_id not in group_registry:
            # First scene in this group — register it
            group_registry[group_id] = (scene_id, env_anchor)
        else:
            # Subsequent scene — ensure continuity prefix is present
            first_id, anchor = group_registry[group_id]
            prompt = scene.get("visual_prompt", "")
            continuity_prefix = f"Continuous from scene {first_id}"

            if not prompt.startswith(continuity_prefix):
                anchor_clause = f"{anchor} " if anchor else ""
                scene["visual_prompt"] = (
                    f"{continuity_prefix}. {anchor_clause}{prompt}"
                )

    return scenes
```

### 2D — Wire into post-processing chain

```python
# After LLM scene parse, in order:
scenes = _enforce_primary_kai_spec(scenes)
scenes = _enforce_closing_scene_primary(scenes)
scenes = _propagate_environment_anchors(scenes)
scenes = _enforce_style_footer(scenes)            # ← always last
return scenes
```

---

## FIX 3 — STYLE FOOTER ENFORCEMENT (post-processing)

### Why

Every visual_prompt must end with a consistent quality/style instruction so
the image generator knows what rendering standard to apply. Currently this
relies entirely on the LLM remembering to add it. When it forgets, images
come back without the photorealistic instruction and quality drops.

Two footer variants based on anchor_role:
- `primary` / `spectator`: includes human quality instructions
- `absent`: symbolic/atmospheric, no human quality instructions needed

### Post-processing function: `_enforce_style_footer`

```python
_STYLE_FOOTER_HUMAN = (
    "Documentary-quality realism, highly detailed human face, realistic eyes, "
    "authentic skin texture, seamless integration with the environment, "
    "no text, no watermark, photorealistic."
)

_STYLE_FOOTER_SYMBOLIC = (
    "No text, no watermark, photorealistic."
)

def _enforce_style_footer(scenes: list[dict]) -> list[dict]:
    """
    Ensures every visual_prompt ends with the correct style/quality footer.
    If the footer is already present (LLM included it), leaves the prompt
    unchanged. If missing, appends the appropriate footer.

    primary / spectator → _STYLE_FOOTER_HUMAN
    absent              → _STYLE_FOOTER_SYMBOLIC
    """
    for scene in scenes:
        role = scene.get("anchor_role", "absent")
        prompt = scene.get("visual_prompt", "").rstrip()

        footer = (
            _STYLE_FOOTER_HUMAN
            if role in ("primary", "spectator")
            else _STYLE_FOOTER_SYMBOLIC
        )

        # Check if the footer's key phrase is already present
        if "photorealistic" not in prompt.lower():
            scene["visual_prompt"] = f"{prompt} {footer}"
        elif role in ("primary", "spectator") and \
                "highly detailed human face" not in prompt.lower():
            # Has 'photorealistic' but missing the human quality instructions
            # Strip the bare 'photorealistic.' and replace with full footer
            import re
            prompt = re.sub(
                r'[,.]?\s*(?:no text[,.]?\s*)?(?:no watermark[,.]?\s*)?photorealistic\.?',
                '',
                prompt,
                flags=re.IGNORECASE
            ).rstrip(" ,.")
            scene["visual_prompt"] = f"{prompt} {footer}"

    return scenes
```

---

## FIX 4 — PROBE COMMAND UPDATE

Update `uv run ytfactory probe <project-dir>` to report scene group information.
Find the probe command in the CLI file.

Add this section to the probe output, after the anchor_role distribution block:

```
scene_group distribution:
  grouped scenes : <n>  (in <m> groups)
  ungrouped      : <n>

Groups:
  <group_id> → scenes <id>, <id>, <id>   [environment_anchor: first 60 chars...]
  <group_id> → scenes <id>, <id>         [environment_anchor: first 60 chars...]

Continuity checks:
  ✔/✗  All grouped scenes (non-first) open with 'Continuous from scene X'
  ✔/✗  All grouped scenes have matching environment_anchor values within group
  ✔/✗  All visual_prompts end with quality footer ('photorealistic' present)
```

Exit code 1 if any continuity check fails (same as existing probe behaviour).

---

## TEST ASSERTIONS

Add to `tests/test_scene_planner.py`:

```python
# ── Character completeness (prompt-level — check via LLM output mocks) ──

def test_no_bare_role_descriptions_in_prompts():
    """
    visual_prompts must not contain bare role-only descriptions.
    'an instructor' / 'some executives' / 'a man in a suit' are violations.
    Detected by checking for these patterns in mock LLM output.
    """
    bare_patterns = [
        "an instructor", "some executives", "a group of executives",
        "a man in a suit", "a woman in a dress"
    ]
    # This test validates the prompt template enforces completeness —
    # use a mock scene that would previously have produced bare descriptions
    # and verify the system prompt addition causes the LLM to expand them.
    # Implementation: snapshot test against known-good output for a fixed input.
    pass  # expand with snapshot approach matching existing test patterns


# ── Scene continuity ──

def test_scene_group_propagation_injects_continuity_prefix():
    """
    Subsequent scene in a group without continuity prefix gets it injected.
    """
    scenes = [
        {
            "scene_id": 5,
            "scene_group_id": "laughing_club_park",
            "environment_anchor": "Manicured urban park at pre-dawn. Cool blue light.",
            "visual_prompt": "Full description of scene 5 with environment.",
            "anchor_role": "spectator",
        },
        {
            "scene_id": 6,
            "scene_group_id": "laughing_club_park",
            "environment_anchor": "Manicured urban park at pre-dawn. Cool blue light.",
            "visual_prompt": "The instructor turns to walk away, collecting payment.",
            "anchor_role": "spectator",
        },
    ]
    result = _propagate_environment_anchors(scenes)
    assert result[1]["visual_prompt"].startswith("Continuous from scene 5")
    assert "Manicured urban park" in result[1]["visual_prompt"]


def test_scene_group_propagation_does_not_double_inject():
    """
    Subsequent scene that already has the continuity prefix is not modified.
    """
    scenes = [
        {
            "scene_id": 5,
            "scene_group_id": "laughing_club_park",
            "environment_anchor": "Manicured urban park at pre-dawn.",
            "visual_prompt": "Scene 5 full prompt.",
            "anchor_role": "spectator",
        },
        {
            "scene_id": 6,
            "scene_group_id": "laughing_club_park",
            "environment_anchor": "Manicured urban park at pre-dawn.",
            "visual_prompt": "Continuous from scene 5. Manicured urban park at pre-dawn. Payment exchange.",
            "anchor_role": "spectator",
        },
    ]
    result = _propagate_environment_anchors(scenes)
    # Must not prepend twice
    assert result[1]["visual_prompt"].count("Continuous from scene 5") == 1


def test_ungrouped_scenes_unaffected_by_propagation():
    """
    Scenes with no scene_group_id are not touched by _propagate_environment_anchors.
    """
    scenes = [
        {
            "scene_id": 3,
            "scene_group_id": None,
            "visual_prompt": "A glowing orb on a cloth. Symbolic.",
            "anchor_role": "absent",
        },
    ]
    result = _propagate_environment_anchors(scenes)
    assert result[0]["visual_prompt"] == "A glowing orb on a cloth. Symbolic."


def test_scene_group_id_field_present_in_model():
    """
    Per-scene Pydantic model has scene_group_id and environment_anchor fields
    with None defaults.
    """
    from ytfactory.agents.nodes.scene_planner import Scene  # adjust import
    s = Scene(scene_id=1, visual_prompt="test", anchor_role="absent")
    assert s.scene_group_id is None
    assert s.environment_anchor is None


# ── Style footer enforcement ──

def test_style_footer_appended_when_missing_primary():
    """Primary scene missing 'photorealistic' gets full human quality footer."""
    scenes = [{"scene_id": 1, "anchor_role": "primary",
               "visual_prompt": "Lean young man at a desk."}]
    result = _enforce_style_footer(scenes)
    assert "photorealistic" in result[0]["visual_prompt"].lower()
    assert "highly detailed human face" in result[0]["visual_prompt"].lower()


def test_style_footer_appended_when_missing_absent():
    """Absent scene missing 'photorealistic' gets symbolic footer only."""
    scenes = [{"scene_id": 1, "anchor_role": "absent",
               "visual_prompt": "A glowing orb on dark cloth."}]
    result = _enforce_style_footer(scenes)
    assert "photorealistic" in result[0]["visual_prompt"].lower()
    assert "highly detailed human face" not in result[0]["visual_prompt"].lower()


def test_style_footer_not_doubled_when_present():
    """Prompt already containing 'photorealistic' is not modified."""
    original = ("Lean young man at a desk. Documentary-quality realism, "
                "highly detailed human face, realistic eyes, authentic skin texture, "
                "seamless integration with the environment, no text, no watermark, "
                "photorealistic.")
    scenes = [{"scene_id": 1, "anchor_role": "primary", "visual_prompt": original}]
    result = _enforce_style_footer(scenes)
    assert result[0]["visual_prompt"].lower().count("photorealistic") == 1


def test_style_footer_upgrades_bare_photorealistic_for_primary():
    """
    Primary scene with bare 'photorealistic' (no human quality instructions)
    gets the full footer substituted.
    """
    scenes = [{"scene_id": 1, "anchor_role": "primary",
               "visual_prompt": "Lean young man at a desk. No text, photorealistic."}]
    result = _enforce_style_footer(scenes)
    assert "highly detailed human face" in result[0]["visual_prompt"].lower()


# ── Probe checks (integration-level) ──

def test_probe_reports_scene_groups(full_pipeline_run):
    """
    Probe output for a run with grouped scenes must include scene group section.
    Smoke test: run probe on a known project dir and check output contains
    'scene_group distribution' and 'Groups:' sections.
    Implementation: use subprocess to run probe and check stdout.
    """
    pass  # expand matching existing probe test patterns
```

---

## IMPLEMENTATION ORDER

1. Add `scene_group_id` and `environment_anchor` to per-scene Pydantic model
2. Add CHARACTER COMPLETENESS RULE + CROSS-SCENE CHARACTER LOCKING RULE to
   scene planner system prompt
3. Add SCENE CONTINUITY RULE to scene planner system prompt (with example)
4. Add `_propagate_environment_anchors` to `scene_planner.py`
5. Add `_enforce_style_footer` to `scene_planner.py`
6. Wire both in post-processing chain (propagate → footer, always last two)
7. Update probe command with scene group reporting + three new continuity checks
8. Add all test assertions to `tests/test_scene_planner.py`
9. Run `uv run pytest tests/test_scene_planner.py -v` — all pass
10. Run `uv run pytest --tb=short -q` — no regressions
11. Re-run Phase 1 on `why-rich-people-pay-to-laugh`
12. Run `uv run ytfactory probe workspace/jobs/why-rich-people-pay-to-laugh`:
    - PASS overall
    - Scene group section shows groups (e.g. laughing_club_park → scenes 5, 6)
    - All continuity checks green
    - All prompts have quality footer
13. Open `IMAGE_PROMPTS.md`:
    - Scenes 5 and 6 share a scene_group_id
    - Scene 6 opens with "Continuous from scene 5. [park environment]..."
    - Scene 6's instructor referenced as "same instructor as in scene 5 — [key descriptors]"
    - All prompts end with appropriate quality footer

---

## TOKEN EFFICIENCY NOTES

- CHARACTER COMPLETENESS + CROSS-SCENE LOCKING: ~260 tokens in system prompt.
  Eliminates all secondary character re-invention across scene groups.
- SCENE CONTINUITY RULE: ~220 tokens including the example. Example is
  load-bearing — do not strip it.
- `_propagate_environment_anchors`: pure Python, zero LLM cost.
- `_enforce_style_footer`: pure Python, zero LLM cost. Deterministic safety
  net — if LLM includes footer, function is a no-op. Cost is one `in` check
  per scene.
- scene_group_id + environment_anchor in JSON: ~30 tokens per grouped scene
  only. Isolated scenes emit null.
- Probe update: UI text addition only, no LLM cost.
- This spec: ~1,400 tokens. Hand to coding agent as-is.
