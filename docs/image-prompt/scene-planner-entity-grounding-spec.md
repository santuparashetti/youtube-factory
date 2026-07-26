# Scene Planner — Entity Grounding Spec
**ytfactory / video_core**
**Version:** 1.0
**Scope:** `src/ytfactory/agents/nodes/scene_planner.py` + prompt templates

---

## Problem Statement

The scene planner LLM hallucinates a **human protagonist** in scenes where
no human appears in the source script. Root cause: the model does semantic
interpolation ("motivational video → man walking") rather than reading *who
is literally present in this narration segment*. This produces visually
coherent images that are **factually wrong** relative to the script — e.g.,
a man standing on a cliff when the narration is about an eaglet learning to fly.

This is a **structural gap**, not a model quality issue. A better model
reduces the frequency, but the architecture must enforce correctness.

---

## Fix: Three Layers

### Layer 1 — Entity Extraction Pass (before prompt generation)

Add a mandatory pre-generation step that extracts **who/what is present** in
each narration segment. This runs once per scene, before the visual_prompt is
written. The output is injected as a hard constraint into the prompt.

#### Where to add it

In `scene_planner.py`, before calling the visual prompt generation chain,
add a call to `_extract_scene_entities(narration: str) -> SceneEntities`.

#### Implementation

```python
# src/ytfactory/agents/nodes/scene_planner.py

from dataclasses import dataclass, field
from typing import Literal

@dataclass
class SceneEntities:
    """
    Who and what are literally present in this narration segment.
    Extracted before visual_prompt generation. Injected as a constraint.
    """
    characters: list[str]          # e.g. ["eagle", "eaglet"] or ["Jerome"] or []
    environment: list[str]         # e.g. ["cliff", "open sky"] or ["workshop"]
    objects: list[str]             # e.g. ["nest", "egg"] or ["copper watch mechanism"]
    has_human: bool                # True only if a human is named or clearly implied
    human_names: list[str]         # ["Bhagiratha", "Vinoba Bhave"] or []
    human_description: str         # "an elderly Indian sage" or "" if has_human=False
    scene_category: Literal[
        "animal_only",             # No humans present at all — animals, nature, objects
        "human_named",             # A specific named historical/story figure
        "human_implied",           # A human is implied but not named ("the boy", "she")
        "abstract",                # Concept-only, no specific character (yoga, seasons)
        "brand_card",              # Closing brand scene
    ]
```

#### Extraction prompt

Call the LLM with this prompt **before** the visual_prompt generation call:

```
ENTITY_EXTRACTION_PROMPT = """
You are a script analyst. Read the following narration segment carefully.

NARRATION:
{narration}

Answer ONLY in JSON. Do not add any explanation.

{{
  "characters": [list every being that is literally present — animal, human, mythological],
  "environment": [list the setting elements mentioned or strongly implied],
  "objects": [list any specific physical objects mentioned],
  "has_human": true/false,
  "human_names": [list only named humans — e.g. "Bhagiratha", "Vinoba Bhave"],
  "human_description": "brief description if a human is present but unnamed, else empty string",
  "scene_category": one of: "animal_only" | "human_named" | "human_implied" | "abstract" | "brand_card"
}}

RULES:
- Only include what is LITERALLY in the narration. Do NOT infer or add.
- If the narration is about an eagle and chick with no human present, has_human = false.
- If the narration says "you feel it within" or "you just watch", that is a VIEWER ADDRESS
  — no human character is present in the scene. has_human = false.
- Poetic/rhetorical questions ("Can Indians not become scientists?") have no characters present.
  scene_category = "abstract".
- A metaphorical human ("one day I too should soar") is NOT a character. has_human = false.
"""
```

---

### Layer 2 — Constrained Visual Prompt Template

The visual_prompt generation prompt must be **parameterized by SceneEntities**.
Replace the current flat `_VISUAL_PROMPTS_TEMPLATE` section with a branching
template that injects entity constraints.

#### Template structure

```python
VISUAL_PROMPT_SYSTEM = """
You are a documentary cinematographer writing image generation prompts.
Your job is to describe ONLY what is in the scene based on the narration.

CRITICAL RULE — ENTITY CONSTRAINT:
The following entities have been extracted from this narration. 
You MUST include ONLY these characters in your prompt.
You MUST NOT add any human figure, person, man, woman, or body part
unless has_human is True.

SCENE ENTITIES:
{entity_block}

VIOLATION EXAMPLES (never do these):
- Narration is about an eagle and chick → prompt adds "a man watching from a cliff" ❌
- Narration is about Bhagiratha → prompt adds a generic man in grey linen ❌  
- Narration is a rhetorical question → prompt shows a specific person ❌

CATEGORY-SPECIFIC RULES:
- animal_only: The subject IS the animal. Show it directly. No human observers.
- human_named: Show the named figure. Ground them in their historical context.
  Do NOT use a generic "man in grey linen shirt" — characterize them specifically.
- human_implied: Show the implied but unnamed human with visual cues from the narration.
- abstract: Use symbolic, environmental, or object-based imagery. No character required.
- brand_card: Follow brand_card template exactly.
"""

def _build_entity_block(entities: SceneEntities) -> str:
    lines = [
        f"scene_category: {entities.scene_category}",
        f"has_human: {entities.has_human}",
    ]
    if entities.characters:
        lines.append(f"characters_present: {', '.join(entities.characters)}")
    if entities.human_names:
        lines.append(f"named_humans: {', '.join(entities.human_names)}")
    if entities.human_description:
        lines.append(f"human_description: {entities.human_description}")
    if entities.environment:
        lines.append(f"environment: {', '.join(entities.environment)}")
    if entities.objects:
        lines.append(f"objects: {', '.join(entities.objects)}")
    return "\n".join(lines)
```

---

### Layer 3 — Faithfulness Validation (post-generation gate)

After the visual_prompt is generated, run a cheap validation call before
writing it to the manifest. This is a second LLM call — use a fast/cheap
model, not the main generation model.

#### Where to add it

In `scene_planner.py`, after the visual_prompt generation call, before
appending the scene to the manifest, call `_validate_prompt_faithfulness()`.

#### Implementation

```python
FAITHFULNESS_VALIDATION_PROMPT = """
You are a QA reviewer for image prompt generation.

NARRATION:
{narration}

SCENE CATEGORY: {scene_category}
HAS_HUMAN: {has_human}

GENERATED VISUAL PROMPT:
{visual_prompt}

Answer ONLY in JSON:
{{
  "pass": true/false,
  "violation": "describe the violation if fail, else empty string",
  "severity": "critical" | "minor" | "none"
}}

CHECK FOR:
1. If has_human=false, does the prompt contain words like: man, woman, person, figure,
   he, she, his, her, hands, face, silhouette, back, profile, standing, walking,
   sitting, crouching? → FAIL (critical)
2. If scene_category="animal_only", is the animal the clear subject? → FAIL if not (critical)
3. If scene_category="human_named", is the named person described specifically
   (not as a generic "man in grey linen")? → FAIL if generic (minor)
4. Does the prompt describe anything NOT in the narration without strong visual justification? → FAIL (minor)
"""

def _validate_prompt_faithfulness(
    narration: str,
    entities: SceneEntities,
    visual_prompt: str,
    llm_client,
) -> tuple[bool, str]:
    """
    Returns (passed: bool, violation_description: str).
    On critical failure, caller should regenerate.
    On minor failure, caller should log and continue.
    Max 1 retry on critical failure — if retry also fails, log and continue
    (don't block the pipeline on validation).
    """
    ...
```

#### Retry logic

```
generate visual_prompt
  → validate
    → pass: write to manifest
    → critical fail: regenerate once with violation injected into prompt
        → validate again
          → pass: write to manifest
          → fail again: write original, set qa_flag="faithfulness_violation" on scene
    → minor fail: write to manifest, set qa_flag="faithfulness_warning" on scene
```

Add `faithfulness_qa` as an optional field on the manifest scene object:

```json
{
  "scene_id": 3,
  "visual_prompt": "...",
  "faithfulness_qa": {
    "status": "pass" | "warning" | "violation",
    "violation": "..."
  }
}
```

---

## Model Recommendation

Switch from `qwen/qwen3-30b-a3b-instruct-2507` to one of the following,
in priority order:

| Priority | Model string (OpenRouter) | Why |
|---|---|---|
| 1st | `google/gemini-2.5-pro` | Best at long-document narrative comprehension; understands the full script arc before writing scene 1; strong cultural context for Indian stories |
| 2nd | `anthropic/claude-sonnet-4-6` | High faithfulness, will not hallucinate characters; already on your LiteLLM infra at `smarthubai.net`, zero friction to add |
| 3rd | `openai/gpt-4o` | Solid, but weaker on Indian cultural grounding than the above two |

**For the entity extraction pass (Layer 1)** — use a cheap/fast model:
`google/gemini-flash-1.5` or `anthropic/claude-haiku-4-5`. It's just JSON
extraction, no creativity needed.

**For the faithfulness validation pass (Layer 3)** — same cheap model.
Only the visual_prompt generation itself needs the main model.

---

## What NOT to Do

- Do not add a post-hoc "find and replace man → eagle" text scrub. That's
  a patch that breaks other scenes where a man *should* appear.
- Do not add a blocklist of words ("no man", "no person" in the system prompt).
  The model will work around it and produce: "a lone figure" or "a silhouette."
  Structural grounding is the only reliable fix.
- Do not make the validation a hard pipeline blocker. Log violations, retry
  once, then continue — the video must complete.

---

## Implementation Checklist for Kilo Code

- [ ] Add `SceneEntities` dataclass to `scene_planner.py`
- [ ] Add `ENTITY_EXTRACTION_PROMPT` constant to `src/ytfactory/agents/prompts/scene_planner.py`
- [ ] Add `_extract_scene_entities(narration, llm_client) -> SceneEntities` method
- [ ] Add `_build_entity_block(entities) -> str` helper
- [ ] Modify `_VISUAL_PROMPTS_TEMPLATE` to accept and inject entity block
- [ ] Add `FAITHFULNESS_VALIDATION_PROMPT` constant
- [ ] Add `_validate_prompt_faithfulness(narration, entities, visual_prompt, llm_client) -> tuple[bool, str]`
- [ ] Wire retry logic (1 retry on critical, log on minor)
- [ ] Add `faithfulness_qa` field to scene manifest schema
- [ ] Add env vars: `ENTITY_EXTRACTION_MODEL` (cheap model), `FAITHFULNESS_VALIDATION_MODEL` (cheap model), `FAITHFULNESS_VALIDATION_ENABLED=true`
- [ ] Add tests: entity extraction for animal-only narration, human-named narration, abstract narration, viewer-address narration ("you feel it within")
- [ ] Add tests: faithfulness validator catches "man" in animal_only prompt, passes correct animal prompt

---

## Test Cases to Write

```python
# Catches the exact bug from this video
def test_entity_extraction_eagle_segment():
    narration = "The chick rose a little. Came down. Tried again."
    entities = _extract_scene_entities(narration, ...)
    assert entities.scene_category == "animal_only"
    assert entities.has_human == False
    assert "eaglet" in entities.characters or "chick" in entities.characters

# Viewer address is NOT a character
def test_entity_extraction_viewer_address():
    narration = "You feel it within. One day, I too should soar up high."
    entities = _extract_scene_entities(narration, ...)
    assert entities.has_human == False
    assert entities.scene_category == "abstract"

# Rhetorical question has no characters
def test_entity_extraction_rhetorical():
    narration = "Can Indians not become mathematicians? Can Indians not become scientists?"
    entities = _extract_scene_entities(narration, ...)
    assert entities.has_human == False
    assert entities.scene_category == "abstract"

# Named figure is extracted correctly
def test_entity_extraction_named_human():
    narration = "Bhagiratha went to the Himalayan peaks. He blocked mountains."
    entities = _extract_scene_entities(narration, ...)
    assert entities.has_human == True
    assert "Bhagiratha" in entities.human_names
    assert entities.scene_category == "human_named"

# Faithfulness validation catches the hallucinated man
def test_faithfulness_catches_man_in_animal_scene():
    entities = SceneEntities(
        characters=["eaglet"],
        scene_category="animal_only",
        has_human=False,
        ...
    )
    bad_prompt = "A lean man stands at the edge of a cliff, watching the sky..."
    passed, violation = _validate_prompt_faithfulness(narration, entities, bad_prompt, ...)
    assert passed == False
    assert "man" in violation.lower()
```
