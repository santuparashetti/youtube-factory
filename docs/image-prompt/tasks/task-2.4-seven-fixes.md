# Task 2.4 — Validator & Generation Fix (7 targeted fixes)
**File scope:** `src/ytfactory/images/validators.py` + `src/ytfactory/agents/nodes/scene_planner.py`
**Do NOT touch:** retry loop, JSON parsing, entity extraction, openai_provider.py, any other file
**Baseline:** 6/26 PASS, 20/26 FAILED after Task 2.3

---

## Token Efficiency Instructions

Apply these to every LLM call in the affected files and any new calls introduced
by this task:

```python
# 1. Enable prompt caching on all system prompts (Anthropic) or use
#    cached_content (Gemini). For OpenAI-compatible (DeepSeek via LiteLLM):
#    pass `extra_body={"cache_prompt": True}` if supported by the proxy.

# 2. Use the minimum max_tokens needed:
#    - Entity extraction responses: max_tokens=300
#    - Validator LLM calls (if any): max_tokens=200
#    - Visual prompt retry: max_tokens=600
#    Never set max_tokens=4096 as a default when 300 is sufficient.

# 3. For batch generation calls (scenes 1-10, 11-20, etc.):
#    Keep batching — do not break into per-scene calls.
#    Each batch call is more token-efficient than N individual calls.

# 4. Strip the full violation message from retry prompts:
#    Send only the violation codes and allowed values, not the full
#    "VALIDATION FAILED — the generated prompt does not match..." preamble.
#    The model doesn't need the preamble to fix the issue.
#    Example — instead of:
#      "VALIDATION FAILED — the generated prompt does not match the Scene Analysis.
#       Please regenerate while preserving the original story, narration...
#       FAILED: FORBIDDEN_CHARACTER — Forbidden character present: 'silhouette'.
#       Hint: Remove forbidden character from the visual prompt."
#    Send:
#      "FAILED: FORBIDDEN_CHARACTER: 'silhouette' — remove it.
#       FAILED: ENVIRONMENT_MISMATCH: must be 'Bird's Nest'."
#    Saves ~60-80 tokens per retry call.

# 5. In the entity extraction prompt, instruct the model to return
#    compact JSON with no explanation:
#    "Return ONLY the JSON object. No explanation, no preamble."
#    Already done via json_mode=True on retries — apply same discipline
#    to entity extraction calls.
```

---

## Fix 1 — `FAIL | 0 errors` still marks scene as FAILED (code bug)

**Observed:** Scene 007 and Scene 022 both show:
```
attempt 2 | FAIL | 0 errors
FAILED after 2 retries | final violation: Prompt failed validation...
```
Zero errors were found but the scene is marked FAILED. The pass/fail
condition has a bug — it's not using `len(errors) == 0` as the pass
condition.

**Fix:** Find the condition that determines pass vs fail after validation.
It must be:
```python
if len(errors) == 0:
    return PASS
else:
    return FAIL
```
If there is any other condition (e.g. a flag, a return value, an exception
path) that can mark a scene failed even when the error list is empty —
remove it. Zero errors = pass, always.

---

## Fix 2 — Article stripping before character matching

**Observed:** Scene 006 fails:
```
UNSUPPORTED_CHARACTER: 'man'
Allowed values: - a man
```
The allowed character is literally `"a man"` but `"man"` is flagged as
unsupported. The comparison is failing because "a " isn't being stripped.

**Fix:** In `is_equivalent_character()` and anywhere character strings are
compared, normalize by stripping leading articles before comparison:

```python
_ARTICLES = {"a ", "an ", "the "}

def _normalize_char(s: str) -> str:
    s = s.lower().strip()
    for article in _ARTICLES:
        if s.startswith(article):
            s = s[len(article):]
            break
    return s
```

Apply `_normalize_char()` to both the detected character and every entry
in `allowed_chars` before any comparison, including inside
`is_equivalent_character()` and the direct match check.

---

## Fix 3 — Verify `is_equivalent_character()` is actually wired

**Observed:** Scene 015 and 024 still flag `"woman"` as
`UNSUPPORTED_CHARACTER` even though `CHARACTER_EQUIVALENTS` maps
`"woman"` → `["she", "her", "mother", "female"]`.

This means `is_equivalent_character()` was implemented but is not being
called in the validation path, OR the equivalence check runs after the
forbidden check and the forbidden check fires first and short-circuits.

**Fix:**
1. In `check_unsupported_character()`, confirm `is_equivalent_character()`
   is called for every detected character before appending a violation.
2. If `FORBIDDEN_CHARACTER` and `UNSUPPORTED_CHARACTER` share detection
   logic, make sure equivalence is checked before the forbidden flag is
   set — don't let a character that IS equivalent get flagged as forbidden.
3. Add a debug log line (DEBUG level) when a character is found equivalent
   and skipped, so this is verifiable in logs.

---

## Fix 4 — Add body-part words to `UNAMBIGUOUS_HUMAN_WORDS`

**Observed:** Scene 001 fails on `"face"`, Scene 003 on `"profile"`,
Scene 019 on `"shoulder"` — all in `animal_only` scenes with
`human_classification=NO_HUMAN_ALLOWED`. These are genuine violations
(the model generated a human body part in a bird scene) but they weren't
being caught because they weren't in `UNAMBIGUOUS_HUMAN_WORDS`.

**Fix:** Add to `UNAMBIGUOUS_HUMAN_WORDS`:
```python
UNAMBIGUOUS_HUMAN_WORDS = {
    # existing entries (keep all) ...
    # add:
    "face", "faces",
    "profile",
    "shoulder", "shoulders",
    "torso",
    "arm", "arms",
    "leg", "legs",
    "chest",
    "forehead",
    "chin",
    "cheek",
    "eye", "eyes",        # only in animal_only — "eagle's eye" is fine, 
                          # but check scene_category before flagging
    "hand", "hands",      # same — only flag in animal_only
    "finger", "fingers",
}
```

**Important nuance for `eye`, `eyes`, `hand`, `hands`:** These can appear
in animal scenes legitimately ("the eagle's eye", "a bird's eye view").
Only flag them when the word appears without an animal possessive adjacent
to it. Simple heuristic: if the word is preceded within 3 words by an
animal name from the scene's `chars` list, skip it. Otherwise flag.

---

## Fix 5 — Add `"silhouette"` to generation prompt forbidden words

**Observed:** Scenes 002, 005, 008, 020 all fail because the generation
model writes "silhouette" in `animal_only` or `abstract` scenes.
"silhouette" is already a `FORBIDDEN_CHARACTER` in the validator — but
the model keeps generating it across retries because nothing in the
*generation prompt* tells it not to.

**Fix location:** `scene_planner.py` — in the visual prompt generation
prompt template (the system or user prompt sent to the LLM when generating
`visual_prompt` for each scene).

**Add to the generation prompt explicitly:**
```
FORBIDDEN WORDS — never use these in any visual prompt:
- silhouette (describe the actual subject directly instead)
- ethereal glow (use specific, realistic lighting descriptions)
- text (no text, writing, or typography in any image)
- watermark
```

This goes in the section that already lists entity constraints and
forbidden characters, so the model sees it before generating.

---

## Fix 6 — Expand `ABSTRACT_ENVIRONMENTS`

**Observed:** Scene 013 fails `ENVIRONMENT_MISMATCH` because environment
is `"inside his head"` — a clearly abstract/psychological space — but
this phrase wasn't in `ABSTRACT_ENVIRONMENTS`.

**Fix:** Expand the set:
```python
ABSTRACT_ENVIRONMENTS = {
    # existing entries (keep all) ...
    # add:
    "inside his head",
    "inside her head",
    "inside their head",
    "inside the character's head",
    "inside the boy's head",
    "inside the man's head",
    "mental space",
    "inside the mind",
    "the mind",
    "imagination",
    "internal thought",
    "internal monologue",
    "thought space",
    "memory",
    "vision",
    "dream",
    "dreamlike",
    "conceptual",
    "metaphorical space",
}
```

Also make the matching fuzzy rather than exact — check if any
`ABSTRACT_ENVIRONMENTS` entry is a *substring* of the scene's environment
field (lowercased), not just an exact set membership check:

```python
def should_skip_environment_check(scene_env: str) -> bool:
    env_lower = scene_env.lower()
    return any(abstract in env_lower for abstract in ABSTRACT_ENVIRONMENTS)
```

---

## Fix 7 — `sage` and symbolic figures in `abstract` / `no_human_allowed` scenes

**Observed:** Scene 009 (`abstract`, `no_human_allowed`, `chars=[]`) fails:
```
FORBIDDEN_CHARACTER: 'sage'
```
`"sage"` is in `SYMBOLIC_HUMAN_FIGURES` which exempts it in
`human_symbolic` scenes — but scene 009 is `abstract`, so the exemption
doesn't fire.

**Logic issue:** When a scene has `chars=[]` (no characters extracted),
`human_classification=no_human_allowed`, AND `scene_category=abstract`,
the model sometimes generates a wise-figure archetype because the narration
is philosophical. This is a borderline case. Two options:

**Option A (preferred):** If `scene_category == "abstract"` and
`chars == []`, treat any detected character that is in
`SYMBOLIC_HUMAN_FIGURES` as a warning (log it) rather than a hard
violation. The image generator will produce it; the human QA validator
downstream can catch if it's genuinely problematic.

**Option B (stricter):** If `scene_category == "abstract"` and
`chars == []`, reject all characters including symbolic ones, but add
`"sage"`, `"elder"`, `"figure"` to the forbidden words in the generation
prompt so the model doesn't generate them in the first place.

**Implement Option A** — it unblocks the pipeline without over-restricting
creative choices. Log at WARNING level so it's visible:
```
Scene 009 | symbolic figure 'sage' in abstract scene — allowing (warning only)
```

---

## Verification after fixes

Run Phase 1 once. Expected outcome:

| Scene category | Expected result |
|---|---|
| `animal_only` with birds only | PASS (no silhouette, no face/profile/shoulder) |
| `abstract` with no chars | PASS (sage treated as warning, not violation) |
| `human_implied` with boy/she | PASS (woman/she equivalence wiring fixed) |
| `human_named` | PASS (article stripping: "a man" matches "man") |
| `0 errors` scenes | PASS (bug fixed) |

**Target: 22+/26 PASS**

---

## Implementation Notes (2026-07-26)

**Status: implemented.** All 7 fixes done in `ytfactory/images/validators.py`,
one line change in `agents/nodes/scene_planner.py` (Fix 1's pass/fail
condition), and one addition to `agents/prompts/scene_planner.py` (Fix 5's
generation-prompt forbidden words). Tests: `tests/test_task_2_4_seven_fixes.py`
(17 tests). Full suite re-run to confirm no regressions vs the 2767 baseline.

**Deviations from the doc's exact pseudocode (behavior preserved, wiring adapted
to this file's actual architecture — there's no separate `check_human_classification()`/
`check_unsupported_character()`/`validate_scene()` free functions, it's all
inline in `StoryFidelityValidator.validate()`):**

- **Fix 1:** the bug was `if deterministic_result.passed and legacy_passed:` —
  a scene with zero deterministic errors could still be marked FAILED if the
  separate LLM-based legacy faithfulness check (a Task-2.2-era addition, not
  mentioned in this doc) disagreed. Fixed by making deterministic pass
  unconditional; legacy disagreement is now logged as a warning, never
  blocking. This *is* a one-line change to the retry loop's pass/fail
  condition — the "Do NOT touch: retry loop" note is read as "don't change the
  retry mechanics (attempts/json_mode/parsing)", which Fix 1 doesn't touch.
- **Fix 4:** the animal-possessive-adjacency nuance was implemented exactly as
  scoped — ONLY for `eye`/`eyes`/`hand`/`hands` (per the doc's own "Important
  nuance" paragraph), not for the other newly-added body-part words (face,
  shoulder, torso, etc.), which are flagged unconditionally in `animal_only`
  scenes as the doc's own example (Scenes 001/003/019) requires.
- **Token Efficiency Instructions:** only items achievable without touching
  forbidden files were applied — `ValidationError.to_feedback_block()` /
  `ValidationResult.feedback_text` were compacted (item 4: no more restated
  "VALIDATION FAILED — ..." preamble/trailer, since `build_retry_prompt()`
  already supplies its own framing). Per-call `max_tokens` tuning (item 2) and
  prompt caching (item 1) were **not** implemented — both require adding a
  parameter to / changing `LLMProvider.generate()` in `openai_provider.py`,
  which is explicitly out of scope ("Do NOT touch ... openai_provider.py").
  Batching (item 3) and entity-extraction prompt changes (item 5) were left
  untouched — the latter is explicitly forbidden ("Do NOT touch ... entity
  extraction").

## Test cases to add

```python
def test_zero_errors_is_pass():
    # Scene with empty error list must return PASS, never FAIL
    result = validate_prompt(errors=[])
    assert result.status == "pass"

def test_article_stripped_in_char_match():
    # "man" should match allowed "a man"
    assert is_equivalent_character("man", ["a man"]) is True

def test_article_stripped_woman_she():
    # "woman" should match allowed "she"
    assert is_equivalent_character("woman", ["she", "the boy"]) is True

def test_is_equivalent_character_called_in_unsupported_check():
    # "woman" with allowed=["she"] should produce zero violations
    violations = check_unsupported_character(
        prompt="a woman walks",
        allowed_chars=["she"],
        scene_category="human_implied",
        detected_chars=["woman"],
    )
    assert violations == []

def test_face_flagged_in_animal_only():
    violations = check_human_classification(
        prompt="the bird's face turned toward the sun",
        scene_category="animal_only",
        human_classification="NO_HUMAN_ALLOWED",
        indicators=UNAMBIGUOUS_HUMAN_WORDS,
    )
    assert any("face" in v for v in violations)

def test_abstract_env_inside_head():
    assert should_skip_environment_check("inside his head") is True

def test_abstract_env_substring_match():
    assert should_skip_environment_check("the boy's head (implied mental space)") is True

def test_sage_in_abstract_scene_is_warning_not_error():
    result = validate_scene(
        scene_category="abstract",
        human_classification="NO_HUMAN_ALLOWED",
        chars=[],
        prompt="an ancient sage sits in stillness",
    )
    assert result.status == "pass"  # warning only, not violation
    assert result.has_warnings is True
```

---

## Do NOT change

- Retry loop, JSON parsing, `json_mode` wiring
- `_HUMAN_INDICATORS` — do not add `"human"` (master context invariant)
- Entity extraction
- Any currently passing test (2767 baseline)
- `openai_provider.py`
- Pre-render gate logic
