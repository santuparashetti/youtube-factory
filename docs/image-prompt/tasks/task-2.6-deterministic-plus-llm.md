# Task 2.6 — Deterministic Fixes + LLM Validation Layer
**Files:** `images/validators.py` + `agents/nodes/scene_planner.py` + `agents/prompts/scene_planner.py`
**Baseline:** 13/28 PASS, 15/28 FAILED (went backwards from 15/30)
**Target:** 24+/28 PASS
**Do NOT touch:** retry loop, openai_provider.py signature, entity extraction

---

## Token Efficiency

- LLM validation calls: max_tokens=150 (binary answer + reason, nothing more)
- Use `google/gemini-2.5-flash-lite` for validation — $0.10/$0.40, 423ms latency, available on OpenRouter
  — configure via env var `FAITHFULNESS_VALIDATOR_MODEL` (already set in .env)
- Batch: run LLM validation only on scenes that fail deterministic checks, never on passing scenes
- No new LLM calls on scenes that already PASS deterministic validation

---

## Part 1 — Fix Two Broken Deterministic Checks

### Fix 1A — `ABSTRACT_ENVIRONMENTS` skip not firing

**Observed:** These environment values are not being skipped despite
being clearly abstract/unrepresentable:
- `"implied human existence"`
- `"implied everyday life setting"`
- `"the narrator's mind"`
- `"no specific location"`
- `"nest in the open sky realm"` (too vague to keyword match)

**Root cause:** The fuzzy substring match in `should_skip_environment_check()`
is not catching these because none of the `ABSTRACT_ENVIRONMENTS` entries
are substrings of these values.

**Fix:** Expand `ABSTRACT_ENVIRONMENTS` with the patterns actually appearing,
AND add a catch-all rule: if the environment string starts with `"implied"`,
treat it as abstract regardless of content:

```python
ABSTRACT_ENVIRONMENTS.update({
    "implied human existence",
    "implied everyday life setting",
    "implied",           # catch-all prefix
    "the narrator's mind",
    "narrator's mind",
    "no specific location",
    "no specific",
    "unspecified location",
    "open sky realm",    # too vague — skip
    "realm",             # any "realm" is symbolic
})

def should_skip_environment_check(scene_env: str) -> bool:
    env_lower = scene_env.lower().strip()
    # Catch-all: anything starting with "implied" is abstract
    if env_lower.startswith("implied"):
        return True
    # Catch-all: anything with "no specific" is abstract
    if "no specific" in env_lower:
        return True
    # Catch-all: "realm" signals symbolic/abstract
    if "realm" in env_lower and len(env_lower.split()) <= 5:
        return True
    # Existing substring match
    return any(abstract in env_lower for abstract in ABSTRACT_ENVIRONMENTS)
```

### Fix 1B — Remove `STORY_TIME_MISSING` check entirely

**Observed:** Scene 026 fails `STORY_TIME_MISSING — allowed: day (day of celebration)`.
This check was never in any spec — it appeared from nowhere in the codebase,
likely added during a Task 2.x implementation. It's a semantic check that
cannot work deterministically (the model can't be expected to encode
"day of celebration" in a visual prompt as a literal string).

**Fix:** Find and remove the `STORY_TIME_MISSING` check from `validators.py`
entirely. It should not exist. If it was added as part of a prior task,
remove it now.

---

## Part 2 — LLM Validation for `ENVIRONMENT_MISMATCH` and `HUMAN_CLASSIFICATION_VIOLATED`

These two checks fail most often and share the same problem: they require
semantic understanding that keyword/pattern matching can't reliably provide.
Replace them with a single LLM validation call per scene that checks both
at once.

### Architecture

```
generate visual_prompt
  → deterministic checks (FORBIDDEN_CHARACTER, UNSUPPORTED_CHARACTER, CAMERA_MISSING, SYMBOLIC_REPLACEMENT)
    → all pass → PASS (no LLM call)
    → any fail → retry (existing logic)

  → if only ENVIRONMENT_MISMATCH or HUMAN_CLASSIFICATION_VIOLATED fail:
    → LLM validation call (cheap model, max_tokens=150)
      → LLM says PASS → accept, mark faithfulness_qa.llm_validated=True
      → LLM says FAIL → existing retry logic
```

Only call LLM when the ONLY remaining failures are environment or human
classification. Don't call LLM if there are also FORBIDDEN_CHARACTER or
SYMBOLIC_REPLACEMENT failures — fix those first via retry.

### LLM Validation Prompt

```python
LLM_VALIDATION_PROMPT = """You are a visual prompt reviewer. Answer in JSON only.

SCENE CATEGORY: {scene_category}
HUMAN CLASSIFICATION: {human_classification}
REQUIRED ENVIRONMENT: {environment}
VISUAL PROMPT: {visual_prompt}

Check:
1. ENVIRONMENT: Does the prompt depict a setting that matches or is compatible with the required environment? 
   (Symbolic/abstract imagery that evokes the environment counts as a match.)
2. HUMAN: Does the prompt correctly follow the human classification rule?
   - NO_HUMAN_ALLOWED: no human figures, body parts, or implied human presence
   - HUMAN_REQUIRED / HUMAN_SYMBOLIC / HUMAN_OPTIONAL: appropriate human presence

Return ONLY this JSON, nothing else:
{{"environment_ok": true/false, "human_ok": true/false, "reason": "one sentence"}}"""
```

### Implementation

```python
# In agents/nodes/scene_planner.py

LLM_VALIDATABLE_CHECKS = {"ENVIRONMENT_MISMATCH", "HUMAN_CLASSIFICATION_VIOLATED"}

def _should_use_llm_validation(errors: list[str]) -> bool:
    """
    Use LLM validation only when all remaining errors are environment
    or human classification — checks that need semantic understanding.
    """
    error_types = {e.split(":")[0].strip() for e in errors}
    return bool(error_types) and error_types.issubset(LLM_VALIDATABLE_CHECKS)

def _run_llm_validation(
    scene: SceneAnalysis,
    visual_prompt: str,
    llm_client,  # use cheap model
) -> tuple[bool, str]:
    """
    Returns (passed: bool, reason: str).
    On parse failure, returns (True, "llm_parse_failed") — don't block on failure.
    """
    prompt = LLM_VALIDATION_PROMPT.format(
        scene_category=scene.scene_category,
        human_classification=scene.human_classification,
        environment=scene.environment or "unspecified",
        visual_prompt=visual_prompt,
    )
    try:
        response = llm_client.generate(
            prompt=prompt,
            json_mode=True,
            max_tokens=150,
        )
        data = json.loads(response)
        passed = data.get("environment_ok", True) and data.get("human_ok", True)
        reason = data.get("reason", "")
        return passed, reason
    except Exception as e:
        logger.warning(f"LLM validation parse failed: {e} — accepting prompt")
        return True, f"llm_parse_failed: {e}"
```

### Integration into retry loop

In `_evaluate_result()` or the validation section of `scene_planner_node`:

```python
# After deterministic validation:
if deterministic_errors and _should_use_llm_validation(deterministic_errors):
    llm_passed, llm_reason = _run_llm_validation(scene, visual_prompt, cheap_llm_client)
    if llm_passed:
        logger.info(
            f"Scene {scene_id:03d} | attempt {attempt} | "
            f"LLM validation PASS (overrides deterministic) | {llm_reason}"
        )
        return PASS  # with faithfulness_qa.llm_validated=True
    else:
        logger.warning(
            f"Scene {scene_id:03d} | attempt {attempt} | "
            f"LLM validation FAIL | {llm_reason}"
        )
        # Fall through to normal retry
```

### Faithfulness QA schema update

Add `llm_validated` boolean to the `faithfulness_qa` field on each scene:

```json
{
  "faithfulness_qa": {
    "status": "pass",
    "llm_validated": true,
    "llm_reason": "The forest setting evokes the required symbolic environment"
  }
}
```

### Env vars and wiring — complete, no decisions left for Claude Code

**`.env.example` additions:**
```bash
FAITHFULNESS_LLM_VALIDATION_ENABLED=true
FAITHFULNESS_VALIDATOR_MODEL=google/gemini-2.5-flash-lite
FAITHFULNESS_VALIDATOR_MAX_TOKENS=150
```

**`src/video_core/config/shared_settings.py` additions:**
```python
faithfulness_llm_validation_enabled: bool = Field(default=True, env="FAITHFULNESS_LLM_VALIDATION_ENABLED")
faithfulness_validator_model: str = Field(default="google/gemini-2.5-flash-lite", env="FAITHFULNESS_VALIDATOR_MODEL")
faithfulness_validator_max_tokens: int = Field(default=150, env="FAITHFULNESS_VALIDATOR_MAX_TOKENS")
```

**LLM client instantiation in `scene_planner.py`:**

The existing scene planner already holds a reference to the main LLM client.
The validator LLM must be a SEPARATE client instance using the cheap model,
NOT the main generation model. Instantiate it alongside the main client:

```python
# In scene_planner_node() or wherever the main llm_client is built:
from video_core.providers.llm.factory import get_llm_provider

validation_llm_client = get_llm_provider(
    provider=settings.llm_provider,        # same provider (OpenRouter via anthropic base_url)
    model=settings.faithfulness_validator_model,  # cheap model override
    base_url=settings.anthropic_base_url,  # same proxy
    api_key=settings.anthropic_api_key,    # same key
)
```

The existing `ANTHROPIC_BASE_URL` in `.env` (OpenRouter) already routes
all models including Gemini Flash and Claude Haiku. No new API key or
provider needed. Claude Code must read the actual value from `.env` —
do not hardcode any URL.

**Pass `validation_llm_client` into `_run_llm_validation()`** — do not
use the main generation client for validation calls.

**`settings.faithfulness_llm_validation_enabled` gate:**
```python
if settings.faithfulness_llm_validation_enabled and _should_use_llm_validation(deterministic_errors):
    llm_passed, llm_reason = _run_llm_validation(scene, visual_prompt, validation_llm_client)
    ...
```

**Disable in tests:** In test settings fixtures, set
`faithfulness_llm_validation_enabled=False` to avoid live API calls.
This follows the same pattern as `tts_analytics_enabled=False` in tests
(master context invariant).

---

## Part 3 — Audit and Fix `FORBIDDEN_CHARACTER` false positive on scene 014

**Observed:** Scene 014 fails `FORBIDDEN_CHARACTER — allowed: boy, mother`.
The `FORBIDDEN_CHARACTER` check is flagging a character that IS in the
allowed list. This is a logic error — `FORBIDDEN_CHARACTER` should only
fire when a character is both unsupported AND explicitly forbidden.

**Fix:** Audit the `FORBIDDEN_CHARACTER` check. It should only fire when:
1. The character appears in the prompt AND
2. The character is NOT in `allowed_chars` AND  
3. The character is in the `forbidden_chars` list

If `allowed_chars = ["boy", "mother"]` and the prompt contains "boy",
`FORBIDDEN_CHARACTER` must not fire. The current implementation appears
to be checking `forbidden_chars` independently of `allowed_chars`.

---

## Implementation Notes (2026-07-26)

**Status: implemented.** `tests/test_task_2_6_deterministic_plus_llm.py` (25 tests).

- **Fix 1A/1B/Part 3:** implemented as specified in `validators.py`.
- **Settings placement deviation:** the doc's exact snippet puts the 3 new
  settings in `video_core/config/shared_settings.py` with `Field(..., env=...)`.
  Neither matches this codebase: (1) `Field(env=...)` is pydantic v1 syntax —
  this project's `pydantic-settings` v2 `BaseSettings` maps env vars
  automatically from the plain attribute name, no `Field(env=...)` needed
  anywhere else in either settings file; (2) scene-planner concepts are
  ytfactory-only (`video_core` must never import from `ytfactory` — see
  CLAUDE.md's layering rule), so they belong in `ytfactory/config/settings.py`
  alongside `scene_planner_max_retries` etc., not in the shared, provider-level
  `SharedSettings`. **Also found and fixed while here:** `scene_planner_max_retries`,
  `scene_planner_json_mode`, `scene_planner_strict_schema`, and
  `faithfulness_gate_fail_pipeline` were genuinely duplicated — declared
  identically in both `shared_settings.py` and `ytfactory/config/settings.py`
  (Task 2.2's concurrent-tool episode — see that task's `MASTER_CONTEXT.md`
  entry). Removed the duplicates from `shared_settings.py`; kept them in
  `ytfactory/config/settings.py` where the new Task 2.6 fields also live.
  Added all 7 vars to `.env.example` (none of the Task 2.2–2.6 scene-planner
  vars were in `.env.example` before this).
- **LLM client instantiation deviation:** the doc's pseudocode calls
  `get_llm_provider(provider=..., model=..., base_url=..., api_key=...)` —
  the actual factory signature is `get_llm_provider(settings)` (single arg,
  reads everything from the settings object) and was not changed. Reused the
  existing `_get_cheap_llm(settings, purpose)` pattern (already used for
  `"extraction"`/`"validation"`) with a new `"llm_validation"` purpose key —
  same practical effect (separate client, cheap model override, same
  provider/base_url/api_key) with zero factory signature changes.
- **`max_tokens=150` not wired to the actual API call** — `LLMProvider.generate()`
  has no per-call `max_tokens` parameter, and this doc (like Task 2.4 before
  it) explicitly forbids touching `openai_provider.py`'s signature. The
  `faithfulness_validator_max_tokens` setting exists (per the doc's env-var
  request) but is currently unused/reserved, documented as such in
  `settings.py`. `_run_llm_validation()` calls `generate(prompt, json_mode=True)`
  without it.
- Full suite: no regressions vs the 2795 baseline (final count in
  `MASTER_CONTEXT.md`).

## Tests

```python
def test_abstract_env_implied_prefix():
    assert should_skip_environment_check("implied human existence") is True
    assert should_skip_environment_check("implied everyday life setting") is True

def test_abstract_env_no_specific():
    assert should_skip_environment_check("no specific location") is True

def test_abstract_env_realm():
    assert should_skip_environment_check("open sky realm") is True
    assert should_skip_environment_check("nest in the open sky realm") is True

def test_story_time_missing_not_in_validators():
    # STORY_TIME_MISSING must not exist anywhere in validators.py
    import inspect
    from ytfactory.images import validators
    source = inspect.getsource(validators)
    assert "STORY_TIME_MISSING" not in source

def test_forbidden_character_not_fired_for_allowed_char():
    violations = check_forbidden_character(
        prompt="a young boy walks with his mother",
        allowed_chars=["boy", "mother"],
        forbidden_chars=["silhouette", "figure"],
    )
    assert violations == []

def test_llm_validation_called_only_for_env_human_errors():
    # Only environment and human errors → should use LLM
    assert _should_use_llm_validation(["ENVIRONMENT_MISMATCH — ..."]) is True
    assert _should_use_llm_validation(["HUMAN_CLASSIFICATION_VIOLATED — ..."]) is True
    assert _should_use_llm_validation(["ENVIRONMENT_MISMATCH", "HUMAN_CLASSIFICATION_VIOLATED"]) is True
    # Mix with other errors → don't use LLM (fix structurals first)
    assert _should_use_llm_validation(["ENVIRONMENT_MISMATCH", "FORBIDDEN_CHARACTER"]) is False
    assert _should_use_llm_validation([]) is False

def test_llm_validation_parse_failure_passes():
    # Parse failure should not block — return True
    passed, reason = _run_llm_validation_with_bad_response(...)
    assert passed is True
    assert "llm_parse_failed" in reason

def test_llm_validation_integrated_in_retry_loop():
    # Scene with only ENVIRONMENT_MISMATCH should trigger LLM call
    # and pass when LLM says environment_ok=True
    ...
```

---

## Do NOT change

- Retry loop structure (only adding LLM call inside it)
- `openai_provider.py` signature
- Entity extraction
- `_HUMAN_INDICATORS` (do not add "human")
- `CHARACTER_EQUIVALENTS` — working correctly
- Tests currently passing (2795 baseline)
