# Task 2.3 — Story Fidelity Validator Fix
**ytfactory / scene_planner**
**Priority:** P0 — validator is blocking all 29 scenes, 0/29 pass rate

---

## Context

Task 2.2 (retry engine) is complete and working correctly:
- `json_mode=True` on retry calls — parsing succeeds every time
- Per-scene inline retry loop — batch retry phase is gone
- Detailed failure logging — working

The remaining problem: the story fidelity validator has a 0% pass rate across
all 29 scenes. Root cause: semantic checks are implemented as lexical/pattern
matchers. A well-written cinematic image prompt never literally contains
strings like "perseverance against doubt" or "the emotional beat is reverence"
— it expresses those things through imagery. The validator cannot understand
metaphor, so it fails everything.

**Do NOT touch:** retry loop, JSON parsing, `json_mode`, entity extraction,
`openai_provider.py`. Scope is the story fidelity validator only.

---

## Confirmed Failures From Log (2026-07-26 01:29AM run)

- 0 PASS, 29 FAILED, 1 SKIPPED (brand card) — pre-render gate
- Every scene exhausts all 2 retries and still fails
- `json_mode=True` retries parse correctly — this is NOT a parsing problem
- The validator rules themselves are what keep failing

---

## Fix 1 — Remove Semantic Checks

These checks require LLM comprehension to work correctly. Lexical/pattern
matching cannot determine if an image prompt *embodies* a concept through
imagery. Remove them entirely.

**Remove these rule checks from the validator:**

```
NARRATION_NOT_REPRESENTED
STORY_GOAL_MISSING
EMOTIONAL_BEAT_MISSING
VISUAL_FOCUS_MISSING
PRIMARY_SUBJECT_MISSING
PRIMARY_ACTION_MISSING
```

**Keep these rule checks — they work correctly with lexical matching:**

```
FORBIDDEN_CHARACTER       — exact string match, works
UNSUPPORTED_CHARACTER     — string match (fix in task below)
HUMAN_CLASSIFICATION_VIOLATED — presence check (fix in task below)
CAMERA_MISSING            — regex for shot/angle keywords, works
SYMBOLIC_REPLACEMENT      — specific word detection, works
FORBIDDEN_OBJECT          — exact string match, works
```

**Why it's safe to remove them:** the scene analysis (era, environment, mood,
narrative role, visual style) is already injected into the visual prompt
generation prompt as a hard constraint. The generation model is told what to
produce. The validator's job is to catch structural violations (wrong
characters, missing camera info, forbidden objects) — not to re-verify
whether the cinematic imagery *feels* like the narration. That's a human
judgment call.

---

## Fix 2 — Fix `HUMAN_CLASSIFICATION_VIOLATED` False Positives in Animal Scenes

**Observed bug:** Scene 002 (mother eagle + chick, `animal_only`) is flagging
`HUMAN_CLASSIFICATION_VIOLATED`. The human detector is triggering on animal
pronouns or relational words ("her", "mother", "its") in the visual prompt.

**Key invariant from codebase (do not break):**
> `"human"` is NOT in `_HUMAN_INDICATORS` — it causes false positives
> with "natural human anatomy". This is intentional. Do not add it.

**Fix:** When `scene_category == "animal_only"` or
`human_classification == "NO_HUMAN_ALLOWED"`, apply a stricter filter before
flagging. Pronouns and relational nouns that are ambiguous (apply to both
animals and humans) must not trigger the rule. Only flag on unambiguous
human-specific terms.

```python
# Words that are ambiguous — apply to animals too. Do NOT flag these
# when scene_category == "animal_only".
ANIMAL_SAFE_WORDS = {
    "her", "his", "its", "their", "mother", "father", "parent",
    "young", "little", "small", "creature", "being",
}

# Words that are unambiguously human — always flag these in animal_only scenes
UNAMBIGUOUS_HUMAN_WORDS = {
    # body parts
    "man", "woman", "person", "figure", "boy", "girl", "child",
    "face", "hands", "fingers", "arm", "leg", "torso", "shoulder",
    "silhouette", "profile", "portrait",
    # actions
    "standing", "walking", "sitting", "crouching", "kneeling",
    "running", "holding", "reaching", "gesturing",
}
```

Implementation:

```python
def check_human_classification(
    prompt: str,
    scene_category: str,
    human_classification: str,
    indicators: set[str],  # existing _HUMAN_INDICATORS
) -> list[str]:
    """
    Returns list of violation strings, empty if no violation.
    """
    if human_classification != "NO_HUMAN_ALLOWED":
        return []

    prompt_lower = prompt.lower()
    detected = []

    for indicator in indicators:
        if indicator in prompt_lower:
            # In animal_only scenes, skip ambiguous words
            if scene_category == "animal_only" and indicator in ANIMAL_SAFE_WORDS:
                continue
            detected.append(indicator)

    if not detected:
        return []

    return [
        f"HUMAN_CLASSIFICATION_VIOLATED — Human figure detected "
        f"({', '.join(detected)!r}) but human_classification=NO_HUMAN_ALLOWED. "
        f"Remove all human figures from this scene."
    ]
```

---

## Fix 3 — Fix `UNSUPPORTED_CHARACTER` Exact String Matching

**Observed bugs from log:**
- Scene 015: `UNSUPPORTED_CHARACTER: 'woman'` — allowed chars are `["she", "the boy"]`.
  "woman" and "she" refer to the same character.
- Scene 023: `UNSUPPORTED_CHARACTER: 'elder'` — scene is `human_symbolic`,
  "elder" is a perfectly valid symbolic figure for this category.
- Scene 014: `UNSUPPORTED_CHARACTER: 'boy'` — allowed chars are `["Mother", "Child"]`.
  "boy" = "Child" semantically.

**Fix:** Add a semantic equivalence map. Before flagging a detected character
as unsupported, check if it is a known equivalent of any allowed character.

```python
# Semantic equivalents — if detected word maps to an allowed character word,
# do not flag as unsupported.
CHARACTER_EQUIVALENTS: dict[str, list[str]] = {
    "woman":  ["she", "her", "mother", "female"],
    "man":    ["he", "him", "male", "father"],
    "boy":    ["the boy", "he", "child", "son", "youth", "young man"],
    "girl":   ["she", "the girl", "child", "daughter", "young woman"],
    "child":  ["boy", "girl", "the boy", "the girl", "son", "daughter", "youth"],
    "elder":  ["ancient teacher", "sage", "wise one", "teacher", "master",
               "seeker", "ascetic", "saint", "mahatma"],
    "figure": ["silhouette", "person", "being", "form"],
    "youth":  ["boy", "young man", "he", "child"],
}

def is_equivalent_character(detected: str, allowed_chars: list[str]) -> bool:
    """
    Returns True if `detected` is a semantic equivalent of any character
    in `allowed_chars`. Case-insensitive.
    """
    detected_lower = detected.lower()
    allowed_lower = [c.lower() for c in allowed_chars]

    # Direct match
    if detected_lower in allowed_lower:
        return True

    # Check equivalents of detected word
    equivalents = CHARACTER_EQUIVALENTS.get(detected_lower, [])
    for eq in equivalents:
        if eq in allowed_lower:
            return True

    # Check if any allowed char maps to detected
    for allowed in allowed_lower:
        for eq in CHARACTER_EQUIVALENTS.get(allowed, []):
            if eq == detected_lower:
                return True

    return False
```

Also add special handling for `human_symbolic` scenes: in these scenes, a
symbolic/archetypal human figure ("elder", "sage", "ancient teacher",
"ascetic", "wise figure") is always permitted regardless of the allowed_chars
list. Do not flag these as unsupported characters in `human_symbolic` scenes.

```python
SYMBOLIC_HUMAN_FIGURES = {
    "elder", "sage", "ascetic", "saint", "seeker", "mahatma",
    "ancient teacher", "wise one", "wise figure", "yogi", "monk",
    "hermit", "rishi", "master",
}

def check_unsupported_character(
    prompt: str,
    allowed_chars: list[str],
    scene_category: str,
    detected_chars: list[str],  # output of character detector
) -> list[str]:
    violations = []
    for char in detected_chars:
        char_lower = char.lower()

        # human_symbolic exemption
        if scene_category == "human_symbolic" and char_lower in SYMBOLIC_HUMAN_FIGURES:
            continue

        # semantic equivalence check
        if is_equivalent_character(char_lower, allowed_chars):
            continue

        violations.append(
            f"UNSUPPORTED_CHARACTER — Unsupported character detected: {char!r}. "
            f"Characters may ONLY come from the narration or Scene Analysis."
        )
    return violations
```

---

## Fix 4 — `ENVIRONMENT_MISMATCH` Should Not Block Abstract/Symbolic Scenes

**Observed bug:** `ENVIRONMENT_MISMATCH` fires on scenes where the scene
analysis says `env=ABSTRACT` or `env=internal/psychological space`, but the
generated prompt uses a real-world visual metaphor (a still lake, an open
field) to *represent* that internal space. This is correct cinematic practice.

**Fix:** When `environment` in scene analysis is any of the following values,
skip `ENVIRONMENT_MISMATCH` entirely — these environments cannot be
represented literally:

```python
ABSTRACT_ENVIRONMENTS = {
    "abstract", "internal", "psychological space", "internal/psychological space",
    "unspecified", "mental space", "inside the character's head",
    "internal thought", "symbolic", "dreamlike",
}

def should_skip_environment_check(scene_env: str) -> bool:
    return any(
        abstract_term in scene_env.lower()
        for abstract_term in ABSTRACT_ENVIRONMENTS
    )
```

---

## Expected Outcome After These Fixes

Before: 0/29 PASS, 29/29 FAILED
After (expected): ~22-26/29 PASS, ~3-7/29 FAILED (genuine violations only)

Genuine violations that should still fail:
- A prompt that literally contains a forbidden object (e.g. "office", "wealth")
- A prompt that puts a human figure in a confirmed `animal_only` scene
  (unambiguous human word, not an animal pronoun)
- A prompt missing any camera/shot type
- A `SYMBOLIC_REPLACEMENT` where a symbol fully replaces the literal story
  element ("master" replacing "eagle" in eagle scenes)

---

## Implementation Checklist

**Status: implemented 2026-07-26.** Scope held to `ytfactory/images/validators.py`
(+ one call-site update in `agents/nodes/scene_planner.py` to pass `scene_category`
through, which was required for Fixes 2/3 to activate). Nothing in "Do NOT Change"
was touched.

- [x] Audit current validator file — find where each rule check is implemented
- [x] Remove `NARRATION_NOT_REPRESENTED` check
- [x] Remove `STORY_GOAL_MISSING` check
- [x] Remove `EMOTIONAL_BEAT_MISSING` check
- [x] Remove `VISUAL_FOCUS_MISSING` check
- [x] Remove `PRIMARY_SUBJECT_MISSING` check
- [x] Remove `PRIMARY_ACTION_MISSING` check
- [x] Add `ANIMAL_SAFE_WORDS` set and `UNAMBIGUOUS_HUMAN_WORDS` set (the latter
  replaces the validator's old narrower 7-word inline list). **Deviation:** the
  detection sweep iterates `UNAMBIGUOUS_HUMAN_WORDS` only, not the union with
  `ANIMAL_SAFE_WORDS` — the doc's pseudocode assumes the ambiguous words are
  already part of the base indicator set being swept; in this file they never
  were, and adding them to the sweep unconditionally (even filtering by
  `scene_category`) broke existing passing scenes that don't explicitly declare
  `animal_only` (e.g. "tests its wings" flagged on "its"). `ANIMAL_SAFE_WORDS`
  is still defined and consulted as a safety net if `UNAMBIGUOUS_HUMAN_WORDS`
  ever grows to overlap it.
- [x] Add `CHARACTER_EQUIVALENTS` map and `is_equivalent_character()` function
- [x] Add `SYMBOLIC_HUMAN_FIGURES` set and exemption in the `UNSUPPORTED_CHARACTER` check
- [x] Add `ABSTRACT_ENVIRONMENTS` set and skip logic (`should_skip_environment_check()`)
- [x] Run existing tests — confirm no regressions (full suite: same 1 pre-existing
  unrelated failure as before this task; 6 tests in `test_validators.py` that
  asserted the *removed* checks' old behavior were rewritten to assert the
  checks no longer fire, per the `test_semantic_checks_removed` intent below)
- [x] Add tests (`tests/test_validator_semantic_fix.py`):
  - `test_human_check_skips_pronoun_in_animal_scene` — "her wings spread" in
    `animal_only` does not trigger violation
  - `test_human_check_flags_man_in_animal_scene` — "a man standing" in
    `animal_only` does trigger violation
  - `test_unsupported_char_woman_equals_she` — "woman" not flagged when
    allowed is ["she", "the boy"]
  - `test_unsupported_char_elder_exempt_in_human_symbolic` — "elder" not
    flagged in `human_symbolic` scene
  - `test_environment_mismatch_skipped_for_abstract` — no violation when
    scene env is "internal/psychological space"
  - `test_semantic_checks_removed_from_source` — confirm none of the 6 removed
    checks' code strings exist in `validators.py`

---

## Do NOT Change

- Retry loop (`generate_and_validate_prompt`)
- JSON parsing (`parse_retry_response`)
- `json_mode` parameter wiring in `openai_provider.py`
- Entity extraction (`_extract_scene_entities`)
- `_HUMAN_INDICATORS` — do not add "human" to this set (master context invariant)
- Pre-render gate logic
- Any test currently passing
