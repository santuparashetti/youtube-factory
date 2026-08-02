# KAI SCENE PLANNER ENFORCEMENT — SPEC

**Status:** Ready for implementation  
**Scope:** Scene planner — two targeted fixes  
**Touches:** `src/ytfactory/agents/nodes/scene_planner.py` + scene planner system prompt  
**Found via:** `uv run ytfactory probe workspace/jobs/why-rich-people-pay-to-laugh`  
**Token budget:** Very low — one post-processing function + two prompt additions  

---

## WHY

First real Phase 1 run with the Kai system produced two probe failures:

1. **Closing scene classified as `spectator` instead of `primary`**
   The LLM correctly classified most scenes but the final scene referenced a group/figure
   and defaulted to spectator. The closing scene MUST be primary — Kai's arc completes
   there. The scene planner prompt instruction isn't strong enough to enforce this.

2. **Primary scenes missing Kai compressed spec in `visual_prompt`**
   Scene 1 example: "A single human figure sits slumped in an armchair" — Kai is
   conceptually present but the locked compressed spec is absent. Without it, every image
   generator draws a different-looking person. Visual consistency breaks.

Both are LLM instruction-following gaps. Fix strategy: **programmatic post-processing**
(deterministic, reliable, zero LLM cost) + **prompt strengthening** (reduces frequency
of the gap at source).

---

## FIX 1 — Programmatic post-processing (add to scene_planner.py)

**After the LLM generates all scenes** (after JSON parse, before returning the scene
list), apply these two guards in order:

### Guard A — Closing scene must be primary

```python
KAI_COMPRESSED_SPEC = (
    "Lean young man, late 20s, short dark hair, light stubble, "
    "simple dark shirt, plain trousers, calm expression"
)

def _enforce_closing_scene_primary(scenes: list[dict]) -> list[dict]:
    """
    The last non-asset scene must be anchor_role='primary'.
    If the LLM classified it otherwise, override and prepend Kai spec.
    
    'Asset scene' = any scene where is_asset (or equivalent flag) is True.
    Look at the scene model for the correct field name — likely `is_asset`,
    `scene_type == "asset"`, or similar. If no such distinction exists,
    treat the last scene as the closing scene.
    """
    # Find last non-asset scene index
    closing_idx = None
    for i in reversed(range(len(scenes))):
        if not scenes[i].get("is_asset", False):  # adjust field name to match model
            closing_idx = i
            break
    
    if closing_idx is None:
        return scenes
    
    closing = scenes[closing_idx]
    if closing.get("anchor_role") != "primary":
        closing["anchor_role"] = "primary"
        # Prepend Kai spec if not already present
        prompt = closing.get("visual_prompt", "")
        if not _has_kai_markers(prompt):
            closing["visual_prompt"] = (
                f"{KAI_COMPRESSED_SPEC} — {prompt}"
            )
    
    return scenes
```

### Guard B — All primary scenes must contain Kai spec

```python
KAI_MARKERS = [
    "dark hair", "simple dark shirt", "lean young man",
    "light stubble", "plain trousers"
]

def _has_kai_markers(prompt: str) -> bool:
    prompt_lower = prompt.lower()
    return any(marker in prompt_lower for marker in KAI_MARKERS)


def _enforce_primary_kai_spec(scenes: list[dict]) -> list[dict]:
    """
    Every scene with anchor_role='primary' must have the Kai compressed
    spec present in its visual_prompt. If missing, prepend it.
    """
    for scene in scenes:
        if scene.get("anchor_role") == "primary":
            prompt = scene.get("visual_prompt", "")
            if not _has_kai_markers(prompt):
                scene["visual_prompt"] = (
                    f"{KAI_COMPRESSED_SPEC} — {prompt}"
                )
    return scenes
```

### Wiring

Call both guards after the LLM scene list is parsed, before returning:

```python
# After parsing scenes from LLM output:
scenes = _enforce_primary_kai_spec(scenes)
scenes = _enforce_closing_scene_primary(scenes)   # run after spec guard
return scenes
```

Run `_enforce_primary_kai_spec` first, then `_enforce_closing_scene_primary` —
so if the closing scene is overridden to primary, the spec guard has already
been applied to the rest of the list, and the closing override includes the
prepend logic inline.

---

## FIX 2 — Strengthen scene planner system prompt

In addition to the programmatic guard (which is the reliable enforcement layer),
strengthen the LLM instruction so the model gets it right at source more often —
reducing how often the guard has to fire.

**Find the scene planner system prompt** (inline in scene_planner.py or a companion
.md file — see existing code). Locate the PRIMARY role construction instruction.

**Replace or augment the PRIMARY construction rule with this:**

```
### PRIMARY — STRICT CONSTRUCTION RULE

anchor_role = "primary" means Kai IS the subject. The visual_prompt MUST begin
with the compressed Kai spec, verbatim, before any scene-specific staging.

The compressed spec is fixed. Copy it exactly:
"Lean young man, late 20s, short dark hair, light stubble, simple dark shirt,
plain trousers, calm expression"

Then add " — " and the scene-specific staging (what he is doing, where, the mood).

CORRECT:
"Lean young man, late 20s, short dark hair, light stubble, simple dark shirt,
plain trousers, calm expression — sitting alone in an empty boardroom, hands
flat on the table, staring at the door. Low afternoon light."

WRONG (never do this):
"A man sits alone in an empty boardroom..." [no Kai spec at the start]
"A single human figure..." [too generic — missing the locked spec]
```

**Also add this rule for the closing scene:**

```
### CLOSING SCENE RULE

The last non-asset scene in every video MUST be anchor_role = "primary".
This is the scene where Kai's arc completes — regardless of what the script
says, Kai must be the primary subject here. Do not classify the closing scene
as "spectator" or "absent" under any circumstances.
```

---

## TEST ASSERTIONS

Add to `tests/test_scene_planner.py`:

```python
def test_closing_scene_is_always_primary():
    """
    The last non-asset scene must have anchor_role='primary'
    even when the script content mentions a real figure.
    """
    # Mock LLM to return closing scene as 'spectator'
    # Verify post-processing overrides it to 'primary'
    mock_scenes = [
        {"scene_id": 1, "anchor_role": "primary", "visual_prompt": "Lean young man...", "is_asset": False},
        {"scene_id": 2, "anchor_role": "spectator", "visual_prompt": "A crowd...", "is_asset": False},
    ]
    result = _enforce_closing_scene_primary(mock_scenes)
    assert result[-1]["anchor_role"] == "primary"
    assert _has_kai_markers(result[-1]["visual_prompt"])


def test_primary_spec_prepended_when_missing():
    """
    Primary scenes without Kai spec markers get the spec prepended.
    """
    mock_scenes = [
        {"scene_id": 1, "anchor_role": "primary",
         "visual_prompt": "A single human figure in an empty room."},
    ]
    result = _enforce_primary_kai_spec(mock_scenes)
    assert _has_kai_markers(result[0]["visual_prompt"])
    assert result[0]["visual_prompt"].startswith("Lean young man")


def test_primary_spec_not_doubled_when_already_present():
    """
    Primary scenes that already have the Kai spec are not modified.
    """
    original = "Lean young man, late 20s, short dark hair — sitting at a desk."
    mock_scenes = [
        {"scene_id": 1, "anchor_role": "primary", "visual_prompt": original},
    ]
    result = _enforce_primary_kai_spec(mock_scenes)
    assert result[0]["visual_prompt"] == original


def test_absent_scenes_unaffected_by_guards():
    """
    Guards must not modify absent scenes.
    """
    mock_scenes = [
        {"scene_id": 1, "anchor_role": "absent",
         "visual_prompt": "A cracked hourglass on stone floor.", "is_asset": False},
        {"scene_id": 2, "anchor_role": "primary",
         "visual_prompt": "Lean young man, late 20s, short dark hair — at a window.", "is_asset": True},
    ]
    result = _enforce_primary_kai_spec(mock_scenes)
    result = _enforce_closing_scene_primary(result)
    assert result[0]["anchor_role"] == "absent"
    assert "dark hair" not in result[0]["visual_prompt"]
```

---

## IMPLEMENTATION ORDER

1. Add `KAI_COMPRESSED_SPEC`, `KAI_MARKERS`, `_has_kai_markers()`,
   `_enforce_primary_kai_spec()`, `_enforce_closing_scene_primary()` to
   `scene_planner.py` (or a shared utils module if the project has one)
2. Wire both guards after the LLM scene parse, before return
3. Strengthen the scene planner system prompt (PRIMARY construction rule + closing rule)
4. Add the 4 new test assertions to `tests/test_scene_planner.py`
5. Run `uv run pytest tests/test_scene_planner.py -v` — all pass
6. Run `uv run pytest --tb=short -q` — no regressions
7. Run Phase 1 on `why-rich-people-pay-to-laugh` again (or any script)
8. Run `uv run ytfactory probe <project-dir>` — must show PASS

---

## TOKEN EFFICIENCY NOTES

- Both guard functions are pure Python post-processing — zero LLM calls, negligible cost
- `KAI_COMPRESSED_SPEC` is defined once in scene_planner.py and referenced by both guards
  and by the existing prompt construction logic — single source of truth
- The prompt strengthening reduces guard invocations over time but is not load-bearing —
  the guards are the reliable enforcement layer
- This spec: ~400 tokens. Hand to coding agent as-is.
