# Task 2.7 — Narrative-Visual Bridge: Permanent Architectural Fix
**Files:** `agents/nodes/scene_planner.py` + `agents/prompts/scene_planner.py`
**Problem:** Visual prompt generator operates from style metadata, not narration content.
**Fix:** Insert a narrative-visual bridging pass that derives a concrete visual
anchor from each scene's narration before any prompt is generated.
**Scope:** All scenes, all future videos, zero manual intervention.

---

## Token Efficiency

- One batch LLM call covers all scenes (same batching as current prompt generation)
- Bridge call uses cheap model via `FAITHFULNESS_VALIDATOR_MODEL` (already configured)
- max_tokens=100 per scene anchor — brief directive only
- Net cost per video: ~30 scenes × ~200 tokens = ~6000 tokens ≈ $0.001 at Gemini Flash Lite rates
- No per-scene extra calls — batch the anchors together

---

## Root Cause (Precise)

The visual prompt generation template receives:
- `scene_category`, `human_classification`, `era`, `mood`, `style`, `environment`
- Entity constraints (allowed/forbidden characters)
- Camera/shot rules
- Forbidden words

It does NOT receive:
- The narration text itself as a primary directive
- An explicit answer to "what does this narration show?"

For scenes with `abstract` category and empty `chars`, the model has zero
narrative direction. It defaults to "spiritual documentary aesthetic object."
This is not a model quality issue — it's a missing input issue.

Current broken flow:
```
narration → scene_analysis (era/mood/env/chars)
                ↓
         visual_prompt_generation(metadata only)
                ↓
         wrong prompt (journal, sandal, candle)
```

Fixed flow:
```
narration → scene_analysis (era/mood/env/chars)
                ↓
         narrative_visual_bridge(narration → visual_anchor)
                ↓
         visual_prompt_generation(metadata + visual_anchor)
                ↓
         correct prompt (parents, hands, chapati)
```

---

## Part 1 — Narrative-Visual Bridge Pass

### What it does

A single batch LLM call, run after scene analysis and before prompt generation,
that reads each scene's narration and produces a `visual_anchor` — a one-sentence
directive describing exactly what the image must depict.

### Where it runs

In `agents/nodes/scene_planner.py`, after `_extract_scene_entities()` and
before the batch visual prompt generation calls.

### Implementation

```python
# agents/nodes/scene_planner.py

def _build_visual_anchors(
    scenes: list[dict],
    cheap_llm_client,  # reuse existing cheap client from Task 2.6
) -> dict[int, str]:
    """
    Batch call: given all scenes' narrations, return a visual_anchor
    per scene_id. visual_anchor = one sentence: what the image must show.

    Returns dict[scene_id → visual_anchor_string].
    Falls back to empty string on parse failure (non-blocking).
    """
    # Build compact batch prompt
    scene_lines = []
    for scene in scenes:
        if scene.get("scene_type") == "brand_card":
            continue
        scene_lines.append(
            f"Scene {scene['index']:03d}: {scene['narration'].strip()}"
        )

    batch_text = "\n".join(scene_lines)

    prompt = f"""\
For each scene below, write ONE sentence describing the single most important
visual element to show in the image. Be specific and literal. Name actual
subjects, actions, or objects from the narration.

Rules:
- Do NOT suggest generic spiritual objects (journal, candle, stone, sandal,
  empty chair, abstract light) unless they appear in the narration.
- DO anchor to a person, animal, action, or object named in the narration.
- If narration describes an emotion/philosophy with no literal subject,
  find the closest concrete metaphor the narration itself suggests.

{batch_text}

Return ONLY JSON: {{"001": "anchor sentence", "002": "anchor sentence", ...}}
No explanation, no markdown, no preamble."""

    try:
        response = cheap_llm_client.generate(
            prompt=prompt,
            json_mode=True,
            max_tokens=100 * len(scenes),  # ~100 tokens per scene
        )
        data = json.loads(response)
        # Normalize keys to int
        return {int(k): v for k, v in data.items() if isinstance(v, str) and v.strip()}
    except Exception as e:
        logger.warning(f"Visual anchor batch failed: {e} — proceeding without anchors")
        return {}
```

### Wiring

```python
# After entity extraction, before batch prompt generation:
visual_anchors = _build_visual_anchors(scenes, validation_llm_client)

# Store on each scene for use in prompt generation:
for scene in scenes:
    scene["_visual_anchor"] = visual_anchors.get(scene["index"], "")
```

---

## Part 2 — Inject Anchor into Generation Prompt

In `agents/prompts/scene_planner.py`, in the per-scene visual prompt
generation template, inject the `visual_anchor` as a mandatory first line:

```python
VISUAL_ANCHOR_INJECTION = """\
REQUIRED VISUAL: {visual_anchor}
This is what the image MUST show. Build the entire prompt around this.
All style, lighting, camera, and era decisions serve this required visual.

"""
```

In the prompt formatter:

```python
def format_scene_prompt(scene: dict, ...) -> str:
    anchor = scene.get("_visual_anchor", "")
    anchor_block = ""
    if anchor:
        anchor_block = VISUAL_ANCHOR_INJECTION.format(visual_anchor=anchor)

    return anchor_block + existing_template.format(...)
```

When `visual_anchor` is empty (fallback), the prompt generates normally
as before — no regression on currently passing scenes.

---

## Part 3 — Narration in Generation Prompt (Always)

Regardless of whether the anchor is present, the narration text must
always appear in the per-scene generation prompt. Add it after the anchor:

```python
NARRATION_CONTEXT = """\
NARRATION FOR THIS SCENE:
"{narration}"

The visual prompt must be traceable to something in this narration.
"""
```

This is a permanent addition to every scene's generation prompt.
The model must always be able to see what is being said.

---

## Part 4 — Store Anchors in Scene Plan

Add `visual_anchor` to the scene plan JSON schema so it's auditable:

```json
{
  "index": 12,
  "narration": "When you wake up...",
  "visual_anchor": "A parent kneeling to meet their child's eyes at dawn",
  "visual_prompt": "...",
  "faithfulness_qa": {...}
}
```

This makes it possible to inspect why any prompt was generated the way it was.

---

## Part 5 — Few-Shot Examples in Anchor Prompt

Add these to the `_build_visual_anchors` prompt as examples:

```
EXAMPLES (do not output these, they are guidance only):
- Narration: "parents smiling, children smile too" → "A mother kneeling to her child at dawn, both smiling"
- Narration: "if you use your hands you become a karma yogi" → "Skilled hands shaping clay on a potter's wheel"
- Narration: "cannot master the chapati, cannot fight the empire" → "Hands rolling chapati dough with precise, deliberate pressure"
- Narration: "eagle soared with absolute confidence after eight days" → "An eagle in full flight, wings spread against open sky, from below"
- Narration: "he took a simple flower, turned it into bread, built an empire" → "A marigold beside a freshly baked chapati on a woven plate"
- Narration: "even on a simple bed, if your spirit is alive, you feel like a king" → "Two beds side by side — one ornate and cold, one simple and warmly lit"
```

---

## Env Var

```bash
VISUAL_ANCHOR_ENABLED=true   # default true; set false to disable (fallback to old behavior)
```

Add to `SharedSettings`:
```python
visual_anchor_enabled: bool = Field(default=True, env="VISUAL_ANCHOR_ENABLED")
```

Gate the bridge call:
```python
if settings.visual_anchor_enabled:
    visual_anchors = _build_visual_anchors(scenes, validation_llm_client)
else:
    visual_anchors = {}
```

---

## Implementation Notes (2026-07-26)

**Status: implemented.** `tests/test_task_2_7_narrative_visual_bridge.py` (13 tests).

- Part 1: `_build_visual_anchors()` + `_build_anchor_batch_prompt()` in
  `agents/nodes/scene_planner.py`, wired right after entity extraction /
  before Phase 2 prompt generation. Reuses the Task 2.6
  `_get_cheap_llm(settings, "llm_validation")` client (moved its
  instantiation earlier so both the anchor pass and the later LLM validation
  step share one client instance — no duplicate creation).
- Part 2/3: `_build_anchor_block()` / `_build_narration_context_block()` in
  `agents/prompts/scene_planner.py`, injected per-scene inside
  `build_visual_prompts_prompt()`'s scene-list loop (same place Task 2.5's
  environment block went — this codebase batches scenes per call rather than
  formatting one prompt per scene, so there's no separate `format_scene_prompt()`
  to hook; the shared batch/retry prompt builder is the single integration point).
- Part 4: free — `scene["visual_anchor"]` is set directly on the same dict
  objects that get serialized into `scene-plan.json`, so it's automatically
  present with zero extra persistence code.
- Part 5: few-shot examples included verbatim in the anchor batch prompt.
- **Setting placement deviation** (same reasoning as Task 2.6): `visual_anchor_enabled`
  added to `ytfactory/config/settings.py`, not `SharedSettings` — it's a
  scene-planner-only concept and `video_core` must never import from
  `ytfactory`. Added `VISUAL_ANCHOR_ENABLED=true` to `.env.example`.
- Full suite: no regressions vs the 2820 baseline (final count in
  `MASTER_CONTEXT.md`).

## Tests

```python
def test_visual_anchor_batch_returns_per_scene():
    scenes = [
        {"index": 1, "narration": "parents smiling, children smile"},
        {"index": 2, "narration": "eagle soared in open sky"},
    ]
    anchors = _build_visual_anchors(scenes, mock_llm_client)
    assert 1 in anchors
    assert 2 in anchors
    assert isinstance(anchors[1], str)
    assert len(anchors[1]) > 10

def test_visual_anchor_injected_into_prompt():
    scene = {"index": 1, "narration": "...", "_visual_anchor": "A parent smiling at a child"}
    prompt = format_scene_prompt(scene)
    assert "A parent smiling at a child" in prompt
    assert "REQUIRED VISUAL" in prompt

def test_narration_always_in_prompt():
    scene = {"index": 1, "narration": "test narration text", "_visual_anchor": ""}
    prompt = format_scene_prompt(scene)
    assert "test narration text" in prompt

def test_anchor_missing_does_not_break():
    # If anchor batch fails, generation continues normally
    scene = {"index": 1, "narration": "test", "_visual_anchor": ""}
    prompt = format_scene_prompt(scene)
    assert prompt  # not empty

def test_anchor_stored_in_scene_plan():
    # scene-plan.json must include visual_anchor field
    scene_plan = load_scene_plan(project_id)
    for scene in scene_plan["scenes"]:
        if scene["scene_type"] != "brand_card":
            assert "visual_anchor" in scene

def test_visual_anchor_enabled_false_skips_bridge():
    with settings_override(visual_anchor_enabled=False):
        anchors = _maybe_build_visual_anchors(scenes, client)
    assert anchors == {}

def test_brand_card_excluded_from_anchor_batch():
    scenes = [
        {"index": 28, "narration": "...", "scene_type": "content"},
        {"index": 29, "narration": "Brand Card", "scene_type": "brand_card"},
    ]
    prompt = _build_anchor_batch_prompt(scenes)
    assert "Scene 029" not in prompt
```

---

## Do NOT change

- validators.py
- openai_provider.py signature
- Retry loop structure
- Entity extraction
- `_HUMAN_INDICATORS`
- LLM validation (Task 2.6) — it remains as the final safety net
- Any test currently passing (2820 baseline)

---

## What This Fixes Permanently

Every scene in every future video gets a narration-derived visual anchor
before the generation model writes a single word of the prompt. The model
can no longer drift to generic aesthetics because it is given a specific
directive: "this is what you must show."

The three broken scenes from this run would have received:
- Scene 012: "A parent kneeling to their child at dawn, both smiling"
- Scene 019: "Skilled hands shaping clay or weaving cloth"
- Scene 027: "Hands rolling chapati dough with deliberate, precise pressure"

And those directives would have been the first thing in their generation prompts.
