# SCENE_PLANNER_V2_FIXES_SPEC.md

**Version:** v2.1  
**Token budget:** Read once, implement in one pass. No re-reads.  
**Touches:** ATMA_THEORY_COMPOSER.md, composer/pipeline.py, scene_planner.py (3 methods), faithfulness_qa retry prompt  
**Do NOT touch:** TTS, Phase 2, models, settings, tests unrelated to these 4 fixes  

---

## FIX 1 — Composer Rehook: Prompt + Early Gate

### 1a. ATMA_THEORY_COMPOSER.md

Find the OUTPUT section (or closing structure section). Add this block verbatim alongside
the existing "This is Atma Theory." closing-line instruction:

```
REQUIRED STRUCTURE — REHOOK (mandatory, never omit):

Between the climax-breath beat and the CTA, include a rehook line. The rehook:
- Directly echoes the opening hook's specific image, question, or scene
- Completes the narrative loop opened at the start
- Is ONE sentence, standalone paragraph
- Format: plain sentence, no header, no label

Example — if the opening hook was "Imagine a man who has everything, yet nothing at all."
the rehook might be: "That man still lives in the grand house — but now the chair faces
a different window."

The pipeline validates for the rehook. A missing rehook aborts the run before scene
planning. Do not omit it.
```

### 1b. composer/pipeline.py — Early Rehook Validation

After the composer LLM call returns and before any downstream node runs, add:

```python
def _validate_rehook_present(script_text: str) -> bool:
    """
    Heuristic: rehook exists if any line in the final 25% of the script
    echoes a key noun/phrase from the first 15% of the script.
    Fails fast rather than false-passing.
    """
    lines = [l.strip() for l in script_text.splitlines() if l.strip()]
    if len(lines) < 8:
        return False  # too short to validate, pass through
    opening_window = " ".join(lines[:max(3, len(lines) // 7)]).lower()
    closing_window = " ".join(lines[int(len(lines) * 0.75):]).lower()
    # Extract nouns from opening (words >4 chars, not stopwords)
    _STOP = {"that", "this", "with", "from", "have", "their", "there",
              "where", "which", "about", "would", "could", "should"}
    opening_nouns = {w for w in opening_window.split() if len(w) > 4 and w not in _STOP}
    return any(noun in closing_window for noun in opening_nouns)


# In the composer pipeline method, after script is finalized:
if not _validate_rehook_present(finalized_script):
    raise ComposerRehookMissingError(
        "Composer output missing rehook. Aborting before scene planning. "
        "Re-run to regenerate, or add a rehook manually and resume."
    )
```

Add `ComposerRehookMissingError(PipelineError)` to your error hierarchy.
Log the first 3 lines of the opening window and last 3 lines of the closing window
in the error message to help manual diagnosis.

**Why heuristic not LLM:** An LLM check here would cost an extra call on every run.
The noun-overlap heuristic catches the structural absence (no callback at all) which
is the failure mode seen — not a quality problem but a missing section problem.
If the heuristic false-positives on an edge case, the PRE_RENDER_GATE is the backstop.

---

## FIX 2 — Inject allowed_characters Into _build_structured_prompt()

In `scene_planner.py`, in `_build_structured_prompt()`, find the `user_prompt` string
that currently passes only `narration_text` and `anchor_role`. Replace with:

```python
# Extract from scene_analysis — use .get() defensively
allowed = scene.scene_analysis.get("allowed_characters", []) if scene.scene_analysis else []
forbidden = scene.scene_analysis.get("forbidden_characters", []) if scene.scene_analysis else []
required_env = scene.scene_analysis.get("environment", "") if scene.scene_analysis else ""

character_block = ""
if allowed:
    character_block = f"""
IMMUTABLE CHARACTER CONSTRAINTS — follow exactly, no exceptions:
- Allowed characters: {', '.join(allowed)}
- Forbidden characters: {', '.join(forbidden) if forbidden else 'none'}
- Required environment: {required_env if required_env else 'as narrated'}
- NEVER substitute "man", "woman", "person", "figure", or "people" for a named entity
- Use the EXACT names from the allowed list in character_staging
- If a character name feels generic (e.g. "villager"), use it verbatim — do not upgrade
  to "man" or "woman"
"""

user_prompt = f"""
SCENE NARRATION:
{scene.narration_text}

KAI ROLE IN THIS SCENE: {scene.anchor_role}
{kai_profile if scene.anchor_role != 'absent' else ''}
{character_block}
"""
```

**Note:** `scene_analysis` may be a dict (JSON-loaded) or a Pydantic model — check the
actual type in the codebase and use attribute access or `.get()` accordingly.

---

## FIX 3 — Retry Immutability Block in faithfulness_qa

Locate the retry/repair prompt in the faithfulness_qa module (or wherever
`_refine_prompt_from_score` / the retry loop lives). Find the system or user prompt
sent on retry attempts 2 and 3. Add this block at the TOP of that prompt, before
the violation description:

```
REPAIR CONTRACT — read before fixing:
1. Fix ONLY the violation type listed below. Touch nothing else.
2. CHARACTER NAMES ARE IMMUTABLE. Do not rename, remove, or substitute any character.
   If the violation is UNSUPPORTED_CHARACTER, remove the offending generic term
   ("man", "woman", "person") and replace with the allowed character name — do not
   remove the character from the scene.
3. ENVIRONMENT IS IMMUTABLE. Do not change the setting, location, or time of day.
4. You may rephrase descriptions freely as long as rules 2 and 3 are preserved.
5. Return only the repaired prompt. No explanation.
```

If the retry prompt doesn't currently pass the `allowed_characters` list, add it here
too — same format as Fix 2's character_block. The repairer needs to know what names
are valid or it can't substitute correctly.

---

## FIX 4 — Camera Angle Variety + Continuity Check

### 4a. _build_structured_prompt() — Add Camera Angle Guidance

After the `arc_phase` is computed, add:

```python
_CAMERA_ANGLE_BY_PHASE = {
    "opening": (
        "eye_level or high_angle — frame characters small against large environments, "
        "emphasise isolation and the scale of the constructed world around them"
    ),
    "build": (
        "eye_level or low_angle — character begins to have presence and agency; "
        "low_angle when a moment of realisation or authority is depicted"
    ),
    "climax": (
        "low_angle or eye_level — maximum character agency; "
        "low_angle for the peak moment of clarity or choice"
    ),
    "resolution": (
        "high_angle easing to eye_level — earned distance; "
        "the world is the same but the character's relationship to it has changed"
    ),
}

camera_angle_guidance = _CAMERA_ANGLE_BY_PHASE.get(arc_phase, "eye_level")
```

Inject into the `bible_context` block (or the system prompt) as one line:

```python
f"- Recommended camera angle for {arc_phase} phase: {camera_angle_guidance}\n"
```

### 4b. _validate_visual_continuity() — Add 5th Check

After the existing 4 checks, add:

```python
# Check 5: Camera angle variety
camera_angles = [
    s.structured_prompt.camera_angle
    for s in scenes
    if s.structured_prompt
]
if camera_angles:
    most_common_angle = max(set(camera_angles), key=camera_angles.count)
    angle_ratio = camera_angles.count(most_common_angle) / len(camera_angles)
    if angle_ratio > 0.75:
        warnings.append(
            f"CONTINUITY: camera_angle '{most_common_angle}' used in "
            f"{camera_angles.count(most_common_angle)}/{len(camera_angles)} scenes "
            f"({angle_ratio:.0%}). Add low_angle and high_angle variety per arc phase."
        )
```

---

## TESTS

Add to `tests/test_scene_planner.py`:

1. `test_allowed_characters_injected_into_prompt()` — scene with non-empty
   `scene_analysis.allowed_characters` → character_block appears in user_prompt
2. `test_forbidden_generic_terms_noted_in_prompt()` — "man", "woman" mentioned
   in the immutability block when allowed_characters is non-empty
3. `test_camera_angle_guidance_in_system_prompt()` — each arc phase produces
   non-eye_level guidance string in the injected context
4. `test_continuity_warning_camera_angle_monotony()` — 20/23 scenes eye_level
   → warning emitted
5. `test_rehook_validator_detects_missing_rehook()` — script with no closing
   echo of opening nouns → returns False
6. `test_rehook_validator_passes_valid_rehook()` — script where closing window
   contains opening noun → returns True

Add to `tests/test_composer.py` (or nearest composer test file):

7. `test_composer_pipeline_raises_on_missing_rehook()` — mock composer output
   with no rehook → `ComposerRehookMissingError` raised before scene planning

---

## DO NOT IMPLEMENT

- LLM-based rehook quality check (heuristic is sufficient for structural absence)
- Changes to `_refine_prompt_from_score` scoring logic
- Any change to the PRE_RENDER_GATE score threshold
- Any model field additions (no new Pydantic fields needed for these fixes)
- Phase 2 changes

---

*End of SCENE_PLANNER_V2_FIXES_SPEC.md*
