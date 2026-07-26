# Task 2.2 — Retry Engine Reliability & Strict Structured Output
**ytfactory / scene_planner**
**Priority:** P0 — blocks quality gate correctness

---

## Confirmed Root Cause (from log analysis — do not guess)

The log tells us exactly what is happening. Read this sequence:

```
23:55:04 — Story fidelity violation scene 001: 4 errors — scheduling deterministic retry
23:55:04 — [LLM call fires]
23:55:06 — Story fidelity violation scene 002: 2 errors — scheduling deterministic retry
23:55:06 — [LLM call fires]
...
23:56:16 — → Retrying 24 failed prompt(s)...
23:56:16 — [LLM call fires]
23:56:24 — ERROR: Deterministic retry parse failed for scene 001
23:56:30 — ERROR: Deterministic retry parse failed for scene 002
...
```

**Two separate systems are firing, and they are confused about each other.**

### Root Cause 1 — Two-phase architecture conflict

There are **two validation systems** running in sequence that don't know about each other:

1. **Story fidelity validator** — fires inline, per-scene, immediately after generation.
   - Flags violations and fires a **first retry** (the "Faithfulness violation — retrying once" lines).
   - This retry appears to succeed at generating a new prompt (the pipeline continues).
   - But this retry's output is stored as the visual_prompt.

2. **Deterministic retry engine** — fires in a separate batch phase ("Retrying 24 failed prompt(s)").
   - Fires AFTER all scenes have been processed.
   - Asks the LLM to return structured JSON: `{"scene_id": N, "visual_prompt": "..."}`.
   - Receives a response it cannot parse — parse fails every time.

The deterministic retry is firing on ALL 24 scenes — including scenes where the inline retry already fixed the violation. It doesn't know the first retry happened. It's re-retrying already-resolved scenes with a different prompt format, and the LLM returns a full visual prompt string (not JSON), which the parser can't handle.

**Result:** The faithfulness_qa field gets `"retry parse failed"` written for every scene regardless of actual validation status, because the batch retry runs last and always fails.

### Root Cause 2 — The validator is overcalibrated

The log shows **24 out of 24 scenes** flagged for story fidelity violations. That's a 100% flag rate. This means the story fidelity validator has rules that no generated prompt can pass in its first attempt. Look at the actual violations logged:

```
scene 009: "a man's legs", "he walks", "his stride" — human in no_human_allowed
scene 014: "tiny figures moving along paths" — human in no_human_allowed
scene 016: "hands, artisans" — human in no_human_allowed
scene 017: "elderly man" — human in no_human_allowed
scene 018: "elderly man, his face, his hair" — human in no_human_allowed
scene 019: "elderly man, his shoulder" — human in no_human_allowed
scene 020: birds not primary subject — animal_only violated
scene 024: "a pair of hands", "skin" — human in no_human_allowed
```

Scenes 17, 18, 19 and 24 are **misclassified by the entity extractor**. The narrations for these scenes describe human subjects (elderly teachers, philosophical humans), but the entity extractor is classifying them as `no_human_allowed`. Scene 24 (chapati hands) — `human_requirement: "forbidden"` is actually a valid creative choice, but hands-only should arguably be a special case.

So the fix is **two things, not one**:
1. Fix the retry architecture
2. Fix entity extractor miscategorization for philosophical/abstract human-address narrations

### Root Cause 3 — The retry prompt asks for JSON but the main generation model doesn't return it

The retry LLM call is using the same `openai_provider` with model `deepseek/deepseek-v3.2`. DeepSeek V3 supports JSON mode via `response_format={"type": "json_object"}` on the OpenAI-compatible endpoint. The current code does NOT pass this parameter, so the model returns prose wrapped in markdown fences, which the parser cannot handle.

---

## Architecture Fix — What to Actually Build

### Remove the two-system confusion first

The current flow:
```
generate_prompt → story_fidelity_validator → inline_retry (fires immediately)
                                           ↓
                                    [continues to next scene]
                ↓ (after all scenes done)
deterministic_retry_batch → re-retries ALL flagged scenes → parse fails
```

The correct flow:
```
generate_prompt → entity_grounding_validator → structured_retry (if fails)
                                             → structured_retry again (if still fails)
                                             → mark FAILED (if exhausted)
                                             ↓ (PASS or FAILED, never silent)
                [next scene]
                ↓ (after all scenes done)
pre_render_gate reads faithfulness_qa from each scene → PASS/FAIL summary
```

**Collapse the two systems into one per-scene loop. Eliminate the batch retry phase entirely.**

---

## Phase 1 — Structured Output via API Parameter (highest priority)

Before fixing any prompt or parser, wire `response_format` properly. This alone will fix 80% of parse failures.

### In `openai_provider.py` — add `response_format` support

```python
# In openai_provider.generate() or equivalent:

def generate(
    self,
    prompt: str,
    system: str | None = None,
    temperature: float = 0.7,
    json_mode: bool = False,      # ADD THIS
    json_schema: dict | None = None,  # ADD THIS for strict schema mode
    **kwargs,
) -> str:
    
    request_params = {
        "model": self.model,
        "messages": messages,
        "temperature": temperature,
    }
    
    if json_mode:
        if json_schema:
            # Strict structured output — OpenAI/DeepSeek/Gemini all support this
            request_params["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "scene_retry_response",
                    "strict": True,
                    "schema": json_schema,
                }
            }
        else:
            # Loose JSON mode — guarantees JSON, not schema
            request_params["response_format"] = {"type": "json_object"}
    
    response = self.client.chat.completions.create(**request_params)
    return response.choices[0].message.content
```

### Retry schema to pass as `json_schema`

```python
RETRY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_id": {"type": "integer"},
        "visual_prompt": {"type": "string", "minLength": 50},
        "changes_made": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1
        },
        "violation_addressed": {"type": "string"}
    },
    "required": ["scene_id", "visual_prompt", "changes_made", "violation_addressed"],
    "additionalProperties": False
}
```

**Important:** Not all models via OpenRouter support strict `json_schema` mode. Check DeepSeek V3.2 support. If unavailable, fall back to `json_object` mode (guarantees JSON, not schema). The parser then validates schema manually. Do NOT fall back to prompt-only JSON requests — that's the current broken state.

---

## Phase 2 — Per-Scene Retry Loop (replace batch retry)

Delete the batch retry. Replace with an inline loop per scene.

```python
MAX_RETRY_ATTEMPTS = 2  # configurable via SCENE_PLANNER_MAX_RETRIES env var

def generate_and_validate_prompt(scene, entity_info, llm_client) -> SceneResult:
    """
    Single scene: generate → validate → retry loop → return result.
    Never returns silently. Always sets faithfulness_qa.
    """
    attempt = 0
    last_violation = None
    
    # Initial generation (attempt 0)
    prompt = _generate_visual_prompt(scene, entity_info, llm_client)
    
    while attempt <= MAX_RETRY_ATTEMPTS:
        violation = _validate_faithfulness(prompt, scene, entity_info, llm_client)
        
        if violation is None:
            # PASS
            logger.info(f"Scene {scene.id:03d} | attempt {attempt} | PASS")
            return SceneResult(
                visual_prompt=prompt,
                faithfulness_qa=FaithfulnessQA(status="pass", violation="")
            )
        
        # FAIL — log with detail
        logger.warning(
            f"Scene {scene.id:03d} | attempt {attempt} | FAIL | {violation}"
        )
        
        if attempt >= MAX_RETRY_ATTEMPTS:
            # Exhausted
            logger.error(
                f"Scene {scene.id:03d} | FAILED after {MAX_RETRY_ATTEMPTS} retries | "
                f"final violation: {violation}"
            )
            return SceneResult(
                visual_prompt=prompt,  # keep last attempt
                faithfulness_qa=FaithfulnessQA(
                    status="failed",
                    violation=violation,
                    attempts=attempt + 1
                )
            )
        
        # Retry
        attempt += 1
        logger.info(f"Scene {scene.id:03d} | retrying (attempt {attempt}/{MAX_RETRY_ATTEMPTS})")
        prompt = _retry_visual_prompt(
            scene=scene,
            entity_info=entity_info,
            violation=violation,
            previous_prompt=prompt,
            llm_client=llm_client,
        )
    
    # Should not reach here — defensive
    return SceneResult(
        visual_prompt=prompt,
        faithfulness_qa=FaithfulnessQA(status="failed", violation="retry loop exited unexpectedly")
    )
```

---

## Phase 3 — Retry Prompt (strict JSON output)

```python
RETRY_PROMPT_TEMPLATE = """
You are rewriting a visual image prompt to fix a specific violation.

SCENE ID: {scene_id}
NARRATION: {narration}
SCENE CATEGORY: {scene_category}
HUMAN REQUIREMENT: {human_requirement}
ALLOWED CHARACTERS: {allowed_characters}
FORBIDDEN CHARACTERS: {forbidden_characters}

ORIGINAL PROMPT (contains violation):
{original_prompt}

VIOLATION TO FIX:
{violation}

REQUIRED CHANGES:
{required_changes}

Rewrite the visual prompt to fix this violation while keeping the same cinematic quality,
shot type, mood, and era. The rewritten prompt must not introduce any new violations.

Return ONLY valid JSON matching this exact structure. No explanation, no markdown,
no code fences, no preamble, no apology. Begin your response with {{ and end with }}.

{{
  "scene_id": {scene_id},
  "visual_prompt": "your rewritten prompt here",
  "changes_made": ["change 1", "change 2"],
  "violation_addressed": "brief description of what you fixed"
}}
"""
```

When calling with `json_mode=True`, this prompt works with `json_object` response format.
The model will not prepend markdown because the API enforces JSON output.

---

## Phase 4 — Parser Hardening

```python
import json
import re
from typing import Optional

def parse_retry_response(raw: str, expected_scene_id: int) -> Optional[dict]:
    """
    Parse LLM retry response. Handles: raw JSON, markdown-fenced JSON,
    leading/trailing whitespace, unicode, escaped characters.
    
    Returns None on any parse or schema failure, with detailed logging.
    """
    if not raw or not raw.strip():
        logger.error(f"Scene {expected_scene_id} | retry response is empty")
        return None
    
    text = raw.strip()
    
    # Step 1: Strip markdown fences if present
    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    fence_match = re.search(fence_pattern, text)
    if fence_match:
        text = fence_match.group(1).strip()
        logger.debug(f"Scene {expected_scene_id} | stripped markdown fence from response")
    
    # Step 2: If still not starting with {, try to find JSON object in response
    if not text.startswith("{"):
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            text = text[json_start:json_end]
            logger.debug(f"Scene {expected_scene_id} | extracted JSON object from response")
        else:
            logger.error(
                f"Scene {expected_scene_id} | retry response contains no JSON object\n"
                f"Raw response (first 500 chars):\n{raw[:500]}"
            )
            return None
    
    # Step 3: Parse JSON — log exact error on failure
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(
            f"Scene {expected_scene_id} | JSONDecodeError: {e.msg} "
            f"at line {e.lineno}, column {e.colno} (char {e.pos})\n"
            f"Problematic section:\n{text[max(0, e.pos-50):e.pos+50]}"
        )
        return None
    
    # Step 4: Schema validation
    required_fields = ["scene_id", "visual_prompt", "changes_made", "violation_addressed"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        logger.error(
            f"Scene {expected_scene_id} | schema missing fields: {missing}\n"
            f"Got keys: {list(data.keys())}"
        )
        return None
    
    # Step 5: Field validation
    if data["scene_id"] != expected_scene_id:
        logger.error(
            f"Scene {expected_scene_id} | scene_id mismatch: "
            f"expected {expected_scene_id}, got {data['scene_id']}"
        )
        return None
    
    if not data["visual_prompt"] or len(data["visual_prompt"].strip()) < 50:
        logger.error(
            f"Scene {expected_scene_id} | visual_prompt is empty or too short: "
            f"'{data['visual_prompt'][:100]}'"
        )
        return None
    
    if not isinstance(data["changes_made"], list) or len(data["changes_made"]) == 0:
        logger.error(f"Scene {expected_scene_id} | changes_made is empty or not a list")
        return None
    
    return data
```

---

## Phase 5 — Fix Validator Overcalibration (separate but related)

The validator is flagging 24/24 scenes. This means the entity extractor is miscategorizing scenes. Two specific fixes needed:

### Fix 1 — Scenes 17, 18, 19 are wrongly `no_human_allowed`

The narrations for these scenes are philosophical/viewer-address but they describe timeless human wisdom. The entity extractor correctly identifies no *named* character, but incorrectly classifies them as `animal_only` or `abstract` when a wise elder figure is both appropriate and expected.

**Fix:** Add a `human_symbolic` category to `SceneEntities.scene_category`:

```python
"human_symbolic"  # Human permitted as archetypal/symbolic figure, not named.
                  # Examples: elderly sage for Vedic teachings, artisan hands,
                  # a distant figure in a landscape.
                  # human_requirement = "permitted_symbolic"
```

Entity extractor prompt addition:
```
- human_symbolic: The narration is philosophical or addresses a universal human 
  quality (wisdom, craft, endurance). A symbolic human figure (elderly sage, 
  artisan hands, distant figure) is APPROPRIATE — not forbidden.
  Use this when: the narration contains "ancient teachers", "the wise", 
  "your hands", "your eyes", "your feet", philosophical second-person address.
```

### Fix 2 — Scene 24 (hands making chapati)

The narration says "stand on your own feet, build a meaningful life" — viewer address. Hands-only close-up is a valid symbolic choice. The validator should NOT flag `hands` or `skin` as human violation when `human_requirement = "forbidden"`. Isolated body parts in close-up as symbolic imagery should be an allowed exception.

**Fix:** Add to faithfulness validator:

```python
SYMBOLIC_BODY_PART_EXCEPTION = True  # hands, feet, eyes in extreme close-up
                                      # do not count as human figure violation
                                      # when scene_category = "abstract" or "human_symbolic"
```

### Fix 3 — Scene 20 (birds in Sharad scene)

Validator says birds aren't the primary subject. But `animal_only` requires animal as unambiguous primary. The entity extractor classified this wrong — the narration describes Sharad *season*, not animals. Birds are mentioned but the scene is about the season.

**Fix:** `animal_only` should only be used when the narration's *primary subject* is the animal. "Birds sing and dance" in a sentence about a season → `abstract`, not `animal_only`. The extractor prompt needs this clarification:

```
- animal_only: Use ONLY when the animal IS the story — the subject being described,
  not incidental mention. "The chick flew" → animal_only. 
  "Birds sing in the Sharad season" → abstract (season is the subject).
```

---

## Phase 6 — Pre-render Gate

The gate currently reads `faithfulness_qa.status` from each scene. After this fix, the only valid statuses are: `"pass"`, `"failed"`, `"skipped"` (brand_card). The gate should:

```python
def evaluate_pre_render_gate(scenes: list[Scene]) -> GateResult:
    failed_scenes = [
        s for s in scenes 
        if s.faithfulness_qa.status == "failed"
    ]
    skipped_scenes = [
        s for s in scenes 
        if s.scene_type == "brand_card"
    ]
    passed_scenes = [
        s for s in scenes 
        if s.faithfulness_qa.status == "pass"
    ]
    
    gate_pass = len(failed_scenes) == 0
    
    logger.info(
        f"Pre-render gate: {len(passed_scenes)} PASS, "
        f"{len(failed_scenes)} FAILED, "
        f"{len(skipped_scenes)} SKIPPED (brand)"
    )
    
    if failed_scenes:
        for s in failed_scenes:
            logger.error(
                f"  Scene {s.index:03d} FAILED — {s.faithfulness_qa.violation}"
            )
    
    return GateResult(passed=gate_pass, failed_count=len(failed_scenes))
```

**Do NOT block pipeline on gate failure.** Log it prominently, write to `phase1_report.json`, and let the human decide. These failures are recoverable in Phase 2 by manually fixing the image prompt. Blocking ruins the two-phase design.

---

## Phase 7 — faithfulness_qa Status Enum

Replace the current ad-hoc string with a proper enum in the scene schema:

```python
class FaithfulnessStatus(str, Enum):
    PASS = "pass"            # Validated clean
    FAILED = "failed"        # Exhausted retries, violation unresolved
    SKIPPED = "skipped"      # brand_card or scene type exempt from validation
    # REMOVE: "violation" (ambiguous) and "retry parse failed" (implementation detail)
```

The `"retry parse failed"` string should never appear in output. It's an internal error, not a validation status.

---

## Phase 8 — Logging Target State

After this fix, the log should look like:

```
Scene 001 | attempt 0 | FAIL | 4 errors: [missing_era, missing_shot_type, ...]
Scene 001 | retrying (attempt 1/2) | json_mode=True
Scene 001 | attempt 1 | PASS
Scene 009 | attempt 0 | FAIL | human detected: 'man's legs', 'he walks'
Scene 009 | retrying (attempt 1/2) | json_mode=True  
Scene 009 | attempt 1 | FAIL | human still present: 'the figure'
Scene 009 | retrying (attempt 2/2) | json_mode=True
Scene 009 | attempt 2 | PASS
Scene 018 | attempt 0 | FAIL | elderly man in no_human_allowed scene
Scene 018 | entity category: human_symbolic — validator miscalibrated, skipping violation
Scene 018 | PASS (after category correction)
```

---

## Env Vars to Add

```bash
SCENE_PLANNER_MAX_RETRIES=2           # retry attempts per scene (default 2)
SCENE_PLANNER_JSON_MODE=true          # use response_format json_object on retry calls
SCENE_PLANNER_STRICT_SCHEMA=false     # use json_schema strict mode if model supports it
FAITHFULNESS_GATE_FAIL_PIPELINE=false # gate logs failures but does not block
```

---

## Implementation Checklist for Kilo Code

**Status: implemented 2026-07-26.** See `docs/context/MASTER_CONTEXT.md` (2026-07-26 entry)
for the full file-by-file summary. Notes on deviations/gaps are inline below.

**Step 1 — openai_provider.py**
- [x] Add `json_mode: bool = False` and `json_schema: dict | None = None` params to `generate()`
  (also added to the shared `LLMProvider` base and to deepinfra/groq/ollama/gemini for interface parity)
- [x] Pass `response_format={"type": "json_object"}` when `json_mode=True`
- [x] Pass `response_format={"type": "json_schema", ...}` when `json_schema` is also set
- [x] Add env var `SCENE_PLANNER_JSON_MODE` to toggle (`Settings.scene_planner_json_mode`, default `True`)

**Step 2 — scene_planner.py**
- [x] Delete the batch retry phase ("Retrying N failed prompt(s)")
- [x] Replace with inline per-scene retry loop (Phase 2 above)
- [x] Wire `json_mode=True` on all retry LLM calls
- [x] Wire `parse_retry_response()` as the only parser

**Step 3 — parser**
- [x] Implement `parse_retry_response()` as spec'd in Phase 4 (lives in `ytfactory/images/validators.py`)
- [x] Never log just "retry parse failed" — always log JSONDecodeError details

**Step 4 — entity extractor**
- [x] Add `human_symbolic` category
- [x] Add `permitted_symbolic` to `human_requirement` enum
- [x] Fix `animal_only` vs `abstract` disambiguation rule in extractor prompt
- [ ] Re-verify scenes 17, 18, 19, 20, 24 classify correctly after fix — **not done**, needs a live
      pipeline run against the actual project that produced the log in this doc

**Step 5 — validator**
- [x] Add `SYMBOLIC_BODY_PART_EXCEPTION` — hands/feet/eyes in close-up not flagged as human
- [x] Add `human_symbolic` scenes to validator — flag if a *named* human appears, not a symbolic one
      (implemented as `HumanClassification.HUMAN_SYMBOLIC`, checked against symbolic indicators)

**Step 6 — faithfulness_qa schema**
- [x] Replace ad-hoc status strings with `FaithfulnessStatus` enum (`ytfactory/scenes/models.py`)
- [x] Add `attempts: int` field to qa object
- [x] Remove all occurrences of `"retry parse failed"` from codebase (grep and delete) — confirmed via
      grep; the only remaining occurrence is a debug log message (not a persisted status value)

**Step 7 — pre-render gate**
- [x] Implement `evaluate_pre_render_gate()` as spec'd — named `evaluate_faithfulness_gate()` in
      `ytfactory/images/faithfulness_gate.py` to avoid colliding with the pre-existing, unrelated
      `ytfactory.retention.pre_render_gate` (a retention-scoring gate, different concept, same name)
- [x] Write gate result to `phase1_report.json` under `faithfulness_gate` key (via
      `scenes/faithfulness-gate.json` + `two_phase/pipeline.py::_write_phase1_report()`)
- [x] Gate does NOT block pipeline (logs only)

**Step 8 — tests** (in `tests/test_retry_engine_reliability.py` + `tests/test_json_mode_providers.py`)
- [x] `test_parse_retry_response_raw_json` — clean JSON, no fences
- [x] `test_parse_retry_response_fenced_json` — ```json ... ``` fences stripped
- [x] `test_parse_retry_response_prose_with_json` — embedded JSON extracted
- [x] `test_parse_retry_response_invalid_json` — JSONDecodeError logged with position
- [x] `test_parse_retry_response_schema_mismatch` — missing required field
- [x] `test_parse_retry_response_scene_id_mismatch` — wrong scene_id rejected
- [x] `test_parse_retry_response_empty_prompt` — short prompt rejected
- [ ] `test_retry_loop_pass_on_attempt_1` / `_2` / `_exhausted` — **not written as isolated unit tests**;
      the retry loop is inline in `scene_planner_node` rather than a standalone function, so its
      constituent pieces (parser, validator, gate) are unit-tested instead of the loop end-to-end
- [x] `test_no_batch_retry_phase` — source-scan confirms no "Retrying N failed" log line exists
- [x] `test_entity_human_symbolic_category` — sage/elder narration → human_symbolic
- [x] `test_entity_animal_only_not_incidental` — mocked-LLM tests confirm `_extract_scene_entities()`
      maps an "abstract" response to `scene_category="abstract"` and an unambiguous animal response
      to `"animal_only"` (the disambiguation judgment itself is prompt-level LLM guidance, not
      deterministic code — see Phase 5 Fix 3)
- [x] `test_pre_render_gate_passes_when_all_pass` (as `test_passes_when_all_scenes_pass`)
- [x] `test_pre_render_gate_reports_failed_scenes` (as `test_reports_failed_scenes`)

---

## Cost Impact

Current: Every scene fires a story fidelity validation call + a faithfulness validation call + a deterministic retry call. 24/24 scenes fire all three.

After fix: Scenes that pass initial generation skip retry entirely. Only genuinely failing scenes retry (expected: ~5–8 out of 24 for this content type after validator recalibration). Per-video cost on retry calls drops ~70%.

The `json_mode=True` retry calls are also faster (model doesn't need to generate prose/markdown wrapper) so latency improves too.
