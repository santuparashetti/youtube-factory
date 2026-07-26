# Task 2.5 — Three Targeted Fixes
**Files:** `agents/prompts/scene_planner.py` + `agents/nodes/scene_planner.py`
**Baseline:** 15/30 PASS, 15/30 FAILED
**Target:** 24+/30 PASS
**Do NOT touch:** validators.py, openai_provider.py, retry loop, entity extraction

---

## Token Efficiency

- No new LLM calls introduced by this task
- Prompt additions must be concise — no verbose explanations
- Forbidden words list: one line per word, no prose
- Environment constraint: one line injection, no paragraph

---

## Fix A — Forbidden words to top of generation system prompt

**Problem:** Model generates `face`, `profile`, `shoulder`, `silhouette`
in `animal_only` and `abstract` scenes despite the forbidden list.
It's buried mid-prompt — model doesn't weight it.

**Fix:** In `agents/prompts/scene_planner.py`, move the forbidden words
block to the **very top** of the visual prompt generation system prompt,
before era/entity/environment content. Format:

```
⚠ ABSOLUTE CONSTRAINTS — read before generating:
FORBIDDEN WORDS (never use in any prompt):
- silhouette → describe the actual subject directly
- face, faces → describe expression or gaze without naming anatomy
- profile → use camera angle instead (e.g. "side-angle shot")
- shoulder, shoulders, torso, chest, arm, arms, leg, legs, forehead → forbidden
- eye, eyes → only permitted when preceded by an animal name (e.g. "eagle's eye")
- hand, hands, finger, fingers → only permitted in human_required/human_symbolic scenes
- text, writing, typography, watermark → never in any image prompt
- ethereal glow → use specific lighting (e.g. "golden hour light", "soft diffused light")

ANIMAL_ONLY SCENES: if human_classification=NO_HUMAN_ALLOWED, generate ONLY the
animal subject. No human anatomy, no human observers, no implied human presence.
```

This block must appear before the scene-specific content in every generation call.

---

## Fix B — Environment as hard constraint in per-scene generation prompt

**Problem:** Scenes 007, 009, 013, 021, 024, 027 all fail
`ENVIRONMENT_MISMATCH`. The model ignores the environment field and
substitutes its own setting.

**Fix:** In the per-scene generation prompt (the user-turn content built
per scene), add a dedicated mandatory environment line immediately before
the visual prompt generation instruction:

```python
# In the per-scene prompt builder, after entity block, before generation instruction:
if scene_analysis.environment and scene_analysis.environment not in (
    "unspecified", "abstract", "no specific location", ""
):
    env_block = (
        f"REQUIRED SETTING: {scene_analysis.environment}\n"
        f"The image MUST be set here. Do not use a different location.\n"
    )
else:
    env_block = ""
```

Inject `env_block` directly before the generation instruction line.
When environment is unspecified/abstract, skip the constraint entirely
(don't inject an empty or misleading constraint).

---

## Fix C — Unify the `0 errors → pass` path for scenes 020 and 022

**Problem:** Scene 028 correctly logs:
```
deterministic PASS, legacy faithfulness check disagreed — accepting anyway
```
Scenes 020 and 022 both show `attempt 2 | FAIL | 0 errors` without
that log line, meaning they hit a different code path that doesn't
apply the override.

**Fix:** In `agents/nodes/scene_planner.py`, find ALL places where
validation result is evaluated. The condition `len(errors) == 0 → PASS`
must be applied at every evaluation point, not just the one that
handles scene 028.

Likely cause: scenes 020 and 022 are going through a different branch
(possibly the retry path vs the initial path, or a different validation
call site). Grep for every location that can produce a FAIL result and
ensure each one checks `len(errors) == 0` before marking failed.

The unified logic must be:
```python
if len(deterministic_errors) == 0:
    # Always pass — log if legacy check disagreed
    if legacy_check_failed:
        logger.warning(
            f"Scene {scene_id:03d} | attempt {attempt} | "
            f"deterministic PASS, legacy faithfulness check disagreed "
            f"({legacy_reason}) — accepting anyway (zero deterministic errors = pass)"
        )
    log_pass(scene_id, attempt)
    return PASS
```

This path must be hit for ALL scenes with 0 errors, regardless of
which attempt number or which code branch they are in.

---

## Implementation Notes (2026-07-26)

**Status: implemented.** `tests/test_task_2_5_three_fixes.py` (11 tests).

- **Fix A:** the forbidden-words block from Task 2.4 (mid-prompt) was removed
  and replaced with the doc's expanded "⚠ ABSOLUTE CONSTRAINTS" block at the
  literal start of `_VISUAL_PROMPTS_TEMPLATE` — before the "You are a
  documentary film director..." line.
- **Fix B:** `_build_environment_block()` in `agents/prompts/scene_planner.py`
  injects a per-scene `REQUIRED SETTING: ...` line read from
  `scene["scene_analysis"]["environment"]`, right after that scene's line in
  the batch scene list (this file batches multiple scenes per generation call
  — there's no literal "per-scene prompt" call site — so the constraint is
  injected per scene within the shared batch/retry prompt builder, which both
  `scene_planner.py`'s batch generation and `validators.py`'s
  `build_retry_prompt()` single-scene retry already route through).
- **Fix C:** the real bug was that `deterministic_result.passed` requires zero
  errors of *any* severity (critical AND minor — e.g. `STORY_TIME_MISSING`,
  `CAMERA_MISSING`), while retry feedback (`compose_feedback`) only ever acts
  on `critical_errors`. A minor-only issue therefore blocked PASS with no
  feedback to fix (empty `critical_errors` → generic "Prompt failed
  validation" message), producing exactly the "FAIL | 0 errors" symptom for
  scenes that never hit the Task 2.4 legacy-check path. There was only ever
  one evaluation point in this codebase (Task 2.4 already unified it) — the
  fix was changing its condition from `deterministic_result.passed` to
  `not deterministic_result.critical_errors`.
- Full suite: no regressions vs the 2784 baseline (see `MASTER_CONTEXT.md` for
  the final count).

## Tests to add

```python
def test_forbidden_words_at_top_of_system_prompt():
    # The system prompt string must start with the ABSOLUTE CONSTRAINTS block
    prompt = build_visual_prompt_system_prompt()
    assert prompt.strip().startswith("⚠ ABSOLUTE CONSTRAINTS")

def test_environment_constraint_injected_when_specific():
    scene = SceneAnalysis(environment="bedroom upon waking")
    prompt = build_per_scene_prompt(scene)
    assert "REQUIRED SETTING: bedroom upon waking" in prompt
    assert "Do not use a different location" in prompt

def test_environment_constraint_skipped_when_abstract():
    scene = SceneAnalysis(environment="no specific location")
    prompt = build_per_scene_prompt(scene)
    assert "REQUIRED SETTING" not in prompt

def test_zero_errors_pass_on_retry_attempt():
    # Simulate: attempt 2, 0 deterministic errors, legacy check disagrees
    result = evaluate_validation_result(
        deterministic_errors=[],
        legacy_failed=True,
        legacy_reason="test",
        attempt=2,
    )
    assert result.status == "pass"

def test_zero_errors_pass_regardless_of_attempt_number():
    for attempt in range(3):
        result = evaluate_validation_result(
            deterministic_errors=[],
            legacy_failed=False,
            attempt=attempt,
        )
        assert result.status == "pass"
```

---

## Do NOT change

- `validators.py` — all fixes there are complete
- `openai_provider.py`
- Retry loop structure
- Entity extraction
- `_HUMAN_INDICATORS` — do not add "human"
- Any currently passing test (2784 baseline)
