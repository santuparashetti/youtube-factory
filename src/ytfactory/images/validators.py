"""Story fidelity validators for generated image prompts.

Architecture
────────────
• HumanClassification — replacement for the old HAS_HUMAN boolean.
• ValidationError   — structured validator feedback for retry logic.
• StoryFidelityValidator — scene-analysis-aware prompt checks.
• SymbolismValidator    — prevents symbolic replacement of literal story.
• RealismValidator      — checks scale, anatomy, perspective, proportions.
• compose_feedback()    — builds the structured retry prompt block.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger

from ytfactory.agents.prompts.scene_planner import build_visual_prompts_prompt


class HumanClassification(str, Enum):
    """Granular human-presence classification for validators and retry logic."""

    NO_HUMAN_ALLOWED = "no_human_allowed"
    HUMAN_OPTIONAL = "human_optional"
    HUMAN_REQUIRED = "human_required"
    NAMED_PERSON_REQUIRED = "named_person_required"
    HUMAN_SYMBOLIC = "human_symbolic"


# Plain-English expansions for each classification — used in retry prompts so
# the model understands the RULE, not just the code name.  Note: NO_HUMAN_ALLOWED
# explicitly lists body-part words so the model knows "hands" counts as human.
HUMAN_CLASSIFICATION_RULES: dict[HumanClassification, str] = {
    HumanClassification.NO_HUMAN_ALLOWED: (
        "No people, hands, feet, silhouettes, shadows of people, or any body part. "
        "Objects and environment only."
    ),
    HumanClassification.HUMAN_OPTIONAL: "Human presence is optional — may include or omit.",
    HumanClassification.HUMAN_SYMBOLIC: (
        "Exactly one stylized/abstract human figure. Not photorealistic."
    ),
    HumanClassification.HUMAN_REQUIRED: "One clearly visible human figure present.",
    HumanClassification.NAMED_PERSON_REQUIRED: (
        "The named person from the narration must be clearly present."
    ),
}


# Body-part words that can appear in a NO_HUMAN_ALLOWED scene without implying a
# human figure — e.g. "mountain shoulder", "river arm", "neural brain diagram",
# "finger of land", "leg of the journey". In non-animal_only scenes these are
# excepted from the HUMAN_CLASSIFICATION_VIOLATED check; animal_only scenes use
# _is_animal_possessive_context instead (the stricter path).
# Action words (standing/walking/holding/…) and figure words (silhouette/portrait/…)
# are intentionally absent — they unambiguously require a human agent.
SYMBOLIC_BODY_PART_EXCEPTION: frozenset[str] = frozenset({
    "hand", "hands",
    "foot", "feet",
    "eye", "eyes",
    "arm", "arms",
    "leg", "legs",
    "shoulder", "shoulders",
    "torso",
    "chest",
    "forehead",
    "chin",
    "cheek",
    "finger", "fingers",
})


# ── Task 2.3 — Story Fidelity Validator Fix ─────────────────────────────────────
# Words that are ambiguous — apply to animals too. Do NOT flag these in
# `animal_only` scenes (e.g. "her wings", "the mother eagle").
ANIMAL_SAFE_WORDS: frozenset[str] = frozenset(
    {
        "her", "his", "its", "their", "mother", "father", "parent",
        "young", "little", "small", "creature", "being",
    }
)

# Words that are unambiguously human — used for the NO_HUMAN_ALLOWED check.
# Task 2.4 Fix 4: expanded with body-part words (face/shoulder/torso/arm/leg/
# chest/forehead/chin/cheek/finger) that were genuine misses — e.g. "profile"
# or "shoulder" in an animal_only bird scene is a real violation, not a false
# positive, and previously wasn't in this set at all.
UNAMBIGUOUS_HUMAN_WORDS: frozenset[str] = frozenset(
    {
        "man", "woman", "person", "figure", "boy", "girl", "child",
        "face", "faces", "hands", "hand", "fingers", "finger", "eye", "eyes",
        "arm", "arms", "leg", "legs", "torso", "shoulder", "shoulders",
        "chest", "forehead", "chin", "cheek",
        "silhouette", "profile", "portrait",
        "standing", "walking", "sitting", "crouching", "kneeling",
        "running", "holding", "reaching", "gesturing",
    }
)

# eye/eyes are ambiguous on their own ("the eagle's eye" is legitimate in an
# animal_only scene) — only flagged when NOT immediately preceded by an
# animal name from the scene's characters. See _is_animal_possessive_context().
_ANIMAL_ADJACENCY_WORDS: frozenset[str] = frozenset({"eye", "eyes", "hand", "hands"})

# Cinematic shot / composition vocabulary that overlaps with anatomy words.
# These must NOT trigger HUMAN_CLASSIFICATION_VIOLATED — they are framing
# instructions, not references to a human body. "Profile shot" is a camera
# angle; "portrait" is a framing style; neither signals a human presence on
# its own. Unambiguous human words (man/woman/standing/…) are still blocked.
_CAMERA_TERM_WORDS: frozenset[str] = frozenset({"profile", "portrait"})

# Geographic-distance qualifier words stripped before the environment core-word
# fallback. "auction houses abroad" → core {auction, house} → matched against
# prompt. These describe WHERE a setting sits relative to the viewer, not WHAT
# it looks like, so dropping them prevents spurious mismatches when the prompt
# omits the qualifier while correctly depicting the setting.
# Deliberately excludes indoors/outdoors/inside/outside — those DO change the
# depicted visual (an outdoor market is not an indoor market hall), so they must
# still count toward the core-word match. Deliberately small and closed.
_ENV_QUALIFIER_WORDS: frozenset[str] = frozenset({
    "abroad", "overseas", "nearby", "distant", "foreign",
})

# Semantic equivalents — if a detected "unsupported" character word maps to an
# allowed character word, it is not actually unsupported (e.g. "woman" when
# allowed_characters=["she"]).
CHARACTER_EQUIVALENTS: dict[str, list[str]] = {
    "woman": ["she", "her", "mother", "female"],
    "man": ["he", "him", "male", "father"],
    "boy": ["the boy", "he", "child", "son", "youth", "young man"],
    "girl": ["she", "the girl", "child", "daughter", "young woman"],
    "child": ["boy", "girl", "the boy", "the girl", "son", "daughter", "youth"],
    "elder": [
        "ancient teacher", "sage", "wise one", "teacher", "master",
        "seeker", "ascetic", "saint", "mahatma",
    ],
    "figure": ["silhouette", "person", "being", "form"],
    "youth": ["boy", "young man", "he", "child"],
}

# Symbolic/archetypal human figures always permitted in human_symbolic scenes,
# regardless of the allowed_characters list from Scene Analysis.
SYMBOLIC_HUMAN_FIGURES: frozenset[str] = frozenset(
    {
        "elder", "sage", "ascetic", "saint", "seeker", "mahatma",
        "ancient teacher", "wise one", "wise figure", "yogi", "monk",
        "hermit", "rishi", "master",
    }
)

# Generic human-figure tokens that are STRUCTURALLY REQUIRED when
# human_classification is HUMAN_SYMBOLIC / HUMAN_REQUIRED / NAMED_PERSON_REQUIRED.
# Blocking these via forbidden_characters in those scenes is contradictory —
# the validator already checks that a human IS present; FORBIDDEN_CHARACTER must
# not then reject generic human words that serve that presence.
_GENERIC_HUMAN_TOKENS: frozenset[str] = frozenset({
    "man", "woman", "person", "figure", "human",
    "boy", "girl", "child", "people",
})

# Environments that cannot be represented literally — a real-world visual
# metaphor (a still lake, an open field) standing in for them is correct
# cinematic practice, not a mismatch.
ABSTRACT_ENVIRONMENTS: frozenset[str] = frozenset(
    {
        "abstract", "internal", "psychological space", "internal/psychological space",
        "unspecified", "mental space", "inside the character's head",
        "internal thought", "symbolic", "dreamlike",
        # Task 2.4 Fix 6:
        "inside his head", "inside her head", "inside their head",
        "inside the boy's head", "inside the man's head",
        "inside the mind", "the mind", "imagination",
        "internal monologue", "thought space", "memory", "vision",
        "dream", "conceptual", "metaphorical space",
        # Task 2.6 Fix 1A:
        "implied human existence", "implied everyday life setting",
        "the narrator's mind", "narrator's mind",
        "no specific location", "no specific", "unspecified location",
        "open sky realm",
    }
)


# Task 2.4 Fix 2: leading articles must be stripped before comparison —
# allowed_characters entries like "a man" or "the boy" otherwise never match
# a bare detected token like "man" or "boy".
_ARTICLES: tuple[str, ...] = ("a ", "an ", "the ")


def _normalize_char(s: str) -> str:
    s = s.lower().strip()
    for article in _ARTICLES:
        if s.startswith(article):
            s = s[len(article):]
            break
    return s


def is_equivalent_character(detected: str, allowed_chars: list[str]) -> bool:
    """Return True if `detected` is a semantic equivalent of any character in
    `allowed_chars`. Case-insensitive, article-insensitive ("a man" ~ "man")."""
    detected_norm = _normalize_char(detected)
    allowed_norm = [_normalize_char(c) for c in allowed_chars]

    if detected_norm in allowed_norm:
        return True

    for eq in CHARACTER_EQUIVALENTS.get(detected_norm, []):
        eq_norm = _normalize_char(eq)
        if eq_norm in allowed_norm:
            return True

    for allowed in allowed_norm:
        for eq in CHARACTER_EQUIVALENTS.get(allowed, []):
            if _normalize_char(eq) == detected_norm:
                return True

    return False


def _is_animal_possessive_context(word: str, prompt_lower: str, animal_names: list[str]) -> bool:
    """True if `word` (e.g. "eye", "hand") appears within 3 tokens after an
    animal name from `animal_names` — e.g. "the eagle's eye", "a bird's eye
    view". Word-boundary token match, case-insensitive. Task 2.4 Fix 4."""
    if not animal_names:
        return False

    animal_terms = [re.sub(r"[^a-z]", "", a.lower()) for a in animal_names if a]
    animal_terms = [a for a in animal_terms if a]
    if not animal_terms:
        return False

    tokens = re.findall(r"[a-z']+", prompt_lower)
    for i, tok in enumerate(tokens):
        if re.sub(r"[^a-z]", "", tok) != word:
            continue
        window = tokens[max(0, i - 3): i]
        for w in window:
            cleaned = re.sub(r"[^a-z]", "", w)
            if any(cleaned == a or (len(a) > 3 and a in cleaned) for a in animal_terms):
                return True
    return False


def should_skip_environment_check(scene_env: str) -> bool:
    """True when the Scene Analysis environment is abstract/internal and
    cannot be represented literally — ENVIRONMENT_MISMATCH must not fire.

    Task 2.6 Fix 1A: on top of the substring set, three catch-all rules for
    phrasings too varied to enumerate ("nest in the open sky realm", "implied
    everyday life setting")."""
    scene_env_lower = scene_env.lower().strip()
    if scene_env_lower.startswith("implied"):
        return True
    if "no specific" in scene_env_lower:
        return True
    if "realm" in scene_env_lower and len(scene_env_lower.split()) <= 5:
        return True
    return any(term in scene_env_lower for term in ABSTRACT_ENVIRONMENTS)


def _singularize(word: str) -> str:
    """Strip a trailing plural 's' so "houses" matches "house". Intentionally
    simple — only handles the common regular plural; irregulars are rare in
    environment strings and a miss just falls through to the exact-substring
    path."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def environment_matches(environment: str, prompt_lower: str) -> bool:
    """True when the prompt satisfies the Scene Analysis environment.

    Two-tier match, no numeric thresholds:
      1. Exact substring (fast path, unchanged behaviour).
      2. Core-word fallback: every content word of the environment — after
         dropping generic locational qualifiers (_ENV_QUALIFIER_WORDS) and
         singularising — must appear in the prompt. This tolerates plural /
         qualifier drift ("auction houses abroad" ~ "an auction house") while
         still rejecting a genuinely different setting (a monastery prompt
         lacks "auction"/"house").
    """
    env_lower = environment.lower().strip()
    if env_lower in prompt_lower:
        return True

    core_words = [
        _singularize(w)
        for w in re.findall(r"\b[a-z]+\b", env_lower)
        if len(w) > 2 and w not in _ENV_QUALIFIER_WORDS
    ]
    if not core_words:
        return False  # nothing substantive to match — defer to exact path result
    # Start-boundary only (no trailing \b) so a singularised core word still
    # matches its plural in the prompt ("house" ~ "houses") while a word
    # boundary at the start blocks false hits like "warehouse" for "house".
    return all(
        re.search(r"\b" + re.escape(w), prompt_lower) is not None
        for w in core_words
    )


@dataclass
class ValidationError:
    """Structured validation failure returned by validators."""

    code: str
    message: str
    severity: str = "critical"
    allowed_values: list[str] | None = None
    hint: str = ""
    violated_item: str = ""  # specific term/object that triggered this failure

    def to_feedback_block(self) -> str:
        # One compact line per error.  When violated_item is set we name the
        # specific offender first so the model knows WHAT to remove/add, not
        # just THAT there was a problem.
        line = f"FAILED: {self.code}"
        if self.violated_item and self.allowed_values:
            line += (
                f" — '{self.violated_item}' detected;"
                f" allowed: {', '.join(str(v) for v in self.allowed_values)}"
            )
        elif self.violated_item:
            line += f" — remove '{self.violated_item}'"
        elif self.allowed_values:
            line += f" — allowed: {', '.join(str(v) for v in self.allowed_values)}"
        elif self.hint:
            line += f" — {self.hint}"
        return line


@dataclass
class ValidationResult:
    """Outcome of running validators against one prompt."""

    passed: bool
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def critical_errors(self) -> list[ValidationError]:
        return [e for e in self.errors if e.severity == "critical"]

    @property
    def feedback_text(self) -> str:
        # Task 2.4 token efficiency: no preamble/trailer — build_retry_prompt()
        # already wraps this with "VIOLATION TO FIX:" and its own JSON
        # instructions, so restating them here cost ~60-80 tokens per retry.
        if not self.errors:
            return ""
        return "\n".join(e.to_feedback_block() for e in self.errors)


# ── Story Fidelity Validator ────────────────────────────────────────────────────


class StoryFidelityValidator:
    """Validate a visual prompt against its Scene Analysis.

    Checks:
      - Characters match Scene Analysis (with semantic equivalence — "woman" ~ "she").
      - No invented characters (exempting symbolic figures in human_symbolic scenes).
      - Environment matches (skipped for abstract/internal environments — see
        `should_skip_environment_check()`).
      - Camera information exists.
      - Forbidden characters and objects are absent.
      - Camera constraints are respected.
      - Human presence matches human_classification (animal-safe pronouns
        exempted in animal_only scenes — see Task 2.3).

    Task 2.6 removed the story-time check — another semantic rule (the model
    can't be expected to encode "day of celebration" as a literal string in a
    visual prompt) that was never part of any spec.

    Task 2.3 removed the semantic/lexical checks that required LLM comprehension
    to evaluate correctly (PRIMARY_SUBJECT_MISSING, PRIMARY_ACTION_MISSING,
    NARRATION_NOT_REPRESENTED, STORY_GOAL_MISSING, EMOTIONAL_BEAT_MISSING,
    VISUAL_FOCUS_MISSING) — a cinematic prompt expresses these through imagery,
    not literal string matches, so pattern matching against them had a 0% pass
    rate. Scene Analysis is still injected into visual-prompt generation as a
    hard constraint; the validator's remaining job is to catch structural
    violations, not to judge whether the imagery "feels" like the narration.
    """

    _BANNED_INVENTED: frozenset[str] = frozenset(
        {
            "man",
            "woman",
            "monk",
            "traveller",
            "traveler",
            "sage",
            "observer",
            "narrator",
            "silhouette",
            "child",
            "children",
            "boy",
            "girl",
            "elder",
            "baby",
            "person",
            "people",
            "crowd",
            "audience",
        }
    )

    _CAMERA_MARKERS: tuple[str, ...] = (
        "wide shot",
        "medium shot",
        "close-up",
        "close up",
        "establishing",
        "drone",
        "low angle",
        "high angle",
        "profile",
        "over-the-shoulder",
        "tracking",
        "static",
        "handheld",
        "environmental portrait",
        "wide cinematic",
    )

    def validate(
        self,
        scene_analysis: dict,
        prompt: str,
        narration: str,
        human_classification: HumanClassification | None = None,
        scene_category: str = "",
        visual_anchor: str = "",
    ) -> ValidationResult:
        errors: list[ValidationError] = []
        prompt_lower = prompt.lower()
        # A scene's own required-visual language — the narration plus its
        # visual_anchor (the "REQUIRED VISUAL"). A token the scene is required
        # to depict must never be treated as a forbidden object (see the
        # FORBIDDEN_OBJECT metaphor guard below).
        required_visual_lower = (narration + " " + visual_anchor).lower()
        allowed_characters = [
            c.lower() for c in scene_analysis.get("allowed_characters", [])
        ]
        scene_characters = [
            c.lower() for c in scene_analysis.get("scene_characters", [])
            if c
        ] or allowed_characters
        no_chars_extracted = not scene_analysis.get("characters")

        for token in self._BANNED_INVENTED:
            if re.search(r"\b" + re.escape(token) + r"\b", prompt_lower):
                if scene_category == "human_symbolic" and token in SYMBOLIC_HUMAN_FIGURES:
                    continue
                if scene_category == "abstract" and no_chars_extracted and token in SYMBOLIC_HUMAN_FIGURES:
                    logger.warning(
                        "symbolic figure '{}' in abstract scene (no characters extracted) "
                        "— allowing (warning only)",
                        token,
                    )
                    continue
                if is_equivalent_character(token, scene_analysis.get("allowed_characters", [])):
                    logger.debug(
                        "UNSUPPORTED_CHARACTER check: '{}' is equivalent to an allowed "
                        "character {} — skipping",
                        token,
                        scene_analysis.get("allowed_characters", []),
                    )
                    continue
                errors.append(
                    ValidationError(
                        code="UNSUPPORTED_CHARACTER",
                        message=f"Unsupported character detected: '{token}'.",
                        severity="critical",
                        allowed_values=scene_analysis.get("allowed_characters", []),
                        hint="Characters may ONLY come from the narration or Scene Analysis.",
                        violated_item=token,
                    )
                )
                break

        forbidden_chars = [
            c for c in scene_analysis.get("forbidden_characters", []) if c
        ]
        for forbidden in forbidden_chars:
            if forbidden.lower() in prompt_lower:
                # Task 2.6 Part 3: a term can end up in BOTH forbidden_characters
                # and allowed_characters (an entity-extraction inconsistency,
                # e.g. allowed=["boy","mother"], forbidden accidentally includes
                # "boy"). Forbidden must never override an explicit allow.
                if is_equivalent_character(forbidden, scene_analysis.get("allowed_characters", [])):
                    logger.debug(
                        "FORBIDDEN_CHARACTER check: '{}' is also an allowed "
                        "character {} — skipping",
                        forbidden,
                        scene_analysis.get("allowed_characters", []),
                    )
                    continue
                # Task 2.4 Fix 7 (Option A): a wise-figure archetype ("sage",
                # "elder") in a philosophical abstract scene with no extracted
                # characters is a borderline creative choice, not a hard
                # violation — warn only, let downstream human QA catch it if
                # it's genuinely a problem.
                if scene_category == "abstract" and no_chars_extracted and forbidden.lower() in SYMBOLIC_HUMAN_FIGURES:
                    logger.warning(
                        "symbolic figure '{}' in abstract scene (no characters extracted) "
                        "— allowing (warning only)",
                        forbidden,
                    )
                    continue
                # When the scene requires a human presence (human_symbolic /
                # human_required / named_person_required), blocking generic human
                # tokens like "man" or "person" is self-contradictory — entity
                # extraction can produce this inconsistency. The human-presence
                # check above already gates quality; don't also forbid the words
                # that satisfy it.
                if (
                    human_classification in (
                        HumanClassification.HUMAN_SYMBOLIC,
                        HumanClassification.HUMAN_REQUIRED,
                        HumanClassification.NAMED_PERSON_REQUIRED,
                    )
                    and forbidden.lower() in _GENERIC_HUMAN_TOKENS
                ):
                    logger.debug(
                        "FORBIDDEN_CHARACTER check: '{}' is a generic human token "
                        "but human_classification=%s requires human presence — skipping",
                        forbidden,
                        human_classification.value,
                    )
                    continue
                errors.append(
                    ValidationError(
                        code="FORBIDDEN_CHARACTER",
                        message=f"Forbidden character present in prompt: '{forbidden}'.",
                        severity="critical",
                        allowed_values=scene_analysis.get("scene_characters", []),
                        hint="Remove forbidden character from the visual prompt.",
                        violated_item=forbidden,
                    )
                )
                break

        forbidden_objs = [
            o for o in scene_analysis.get("forbidden_objects", []) if o
        ]
        for forbidden_obj in forbidden_objs:
            if forbidden_obj.lower() in prompt_lower:
                # Metaphor guard: entity extraction can wrongly forbid an object
                # that is the scene's OWN core metaphor / required visual (e.g.
                # "canvas" forbidden on a scene about painting a life onto a
                # canvas). If the object appears in the scene's narration or
                # visual_anchor, it is required, not forbidden — skip it.
                if forbidden_obj.lower() in required_visual_lower:
                    logger.debug(
                        "FORBIDDEN_OBJECT check: '{}' is part of the scene's own "
                        "required visual / narration — skipping",
                        forbidden_obj,
                    )
                    continue
                errors.append(
                    ValidationError(
                        code="FORBIDDEN_OBJECT",
                        message=f"Forbidden object present in prompt: '{forbidden_obj}'.",
                        severity="critical",
                        hint="Remove forbidden object from the visual prompt.",
                        violated_item=forbidden_obj,
                    )
                )
                break

        environment = scene_analysis.get("environment", "")
        if (
            environment
            and not environment_matches(environment, prompt_lower)
            and not should_skip_environment_check(environment)
        ):
            errors.append(
                ValidationError(
                    code="ENVIRONMENT_MISMATCH",
                    message="Environment from Scene Analysis does not match the prompt.",
                    severity="critical",
                    allowed_values=[environment],
                    hint="The setting must match the narration environment.",
                )
            )

        camera_constraints = scene_analysis.get("camera_constraints", "")
        if camera_constraints:
            constraint_terms = [
                term.strip() for term in camera_constraints.lower().split(",") if term.strip()
            ]
            for term in constraint_terms:
                if term.startswith("no "):
                    positive = term[3:].strip()
                    if positive and positive in prompt_lower:
                        errors.append(
                            ValidationError(
                                code="CAMERA_CONSTRAINT_VIOLATED",
                                message=f"Camera constraint violated: '{term}'.",
                                severity="minor",
                                allowed_values=[camera_constraints],
                                hint="The prompt must follow the camera constraints from Scene Analysis.",
                            )
                        )
                        break
                elif term and term not in prompt_lower:
                    errors.append(
                        ValidationError(
                            code="CAMERA_CONSTRAINT_VIOLATED",
                            message=f"Camera constraint not respected: '{term}'.",
                            severity="minor",
                            allowed_values=[camera_constraints],
                            hint="The prompt must follow the camera constraints from Scene Analysis.",
                        )
                    )
                    break

        if not any(marker in prompt_lower for marker in self._CAMERA_MARKERS):
            errors.append(
                ValidationError(
                    code="CAMERA_MISSING",
                    message="No camera/shot information found in the prompt.",
                    severity="minor",
                    hint="Include a specific camera angle or shot type.",
                )
            )

        if human_classification == HumanClassification.NO_HUMAN_ALLOWED:
            detected_human_words: list[str] = []
            # Only unambiguous words trigger this rule. ANIMAL_SAFE_WORDS
            # (pronouns/relational words like "her", "mother", "its") are
            # intentionally NOT part of the detection sweep — they're too
            # ambiguous to ever be a reliable human-presence signal on their
            # own, and would otherwise false-positive on ordinary animal
            # narration ("the mother eagle", "tests its wings") in scenes
            # that were never explicitly marked animal_only. The animal_only
            # skip below still applies to guard against a future expansion of
            # UNAMBIGUOUS_HUMAN_WORDS. See Task 2.3 Fix 2.
            animal_names = scene_analysis.get("characters") or scene_analysis.get("allowed_characters", [])
            for indicator in UNAMBIGUOUS_HUMAN_WORDS:
                if not re.search(r"\b" + re.escape(indicator) + r"\b", prompt_lower):
                    continue
                # Camera/composition vocabulary ("profile shot", "portrait")
                # overlaps with anatomy words but signals framing, not a human
                # body — never a HUMAN_CLASSIFICATION violation on its own.
                if indicator in _CAMERA_TERM_WORDS:
                    continue
                if indicator in _ANIMAL_ADJACENCY_WORDS:
                    # Task 2.4 Fix 4: "eye"/"hand" etc. are only a real violation
                    # in animal_only scenes when NOT immediately preceded by an
                    # animal name ("the eagle's eye" is fine; a bare "the eye"
                    # or "a man's hand" is not). For non-animal scenes these fall
                    # through to the SYMBOLIC_BODY_PART_EXCEPTION check below.
                    if scene_category == "animal_only":
                        if _is_animal_possessive_context(indicator, prompt_lower, animal_names):
                            continue
                # Isolated body-part words (shoulder, arm, brain, hand, etc.) can
                # appear without a human figure in non-animal scenes — mountain
                # shoulder, river arm, neural brain diagram. Action/figure words
                # (standing, silhouette, …) are NOT in SYMBOLIC_BODY_PART_EXCEPTION
                # and still fire unconditionally.
                if scene_category != "animal_only" and indicator in SYMBOLIC_BODY_PART_EXCEPTION:
                    continue
                if scene_category == "animal_only" and indicator in ANIMAL_SAFE_WORDS:
                    continue
                detected_human_words.append(indicator)

            if detected_human_words:
                errors.append(
                    ValidationError(
                        code="HUMAN_CLASSIFICATION_VIOLATED",
                        message=(
                            f"Human figure detected ({', '.join(detected_human_words)!r}) "
                            "but human_classification=NO_HUMAN_ALLOWED."
                        ),
                        severity="critical",
                        hint="Remove all human figures from this scene.",
                        violated_item=", ".join(detected_human_words),
                    )
                )
        elif human_classification == HumanClassification.HUMAN_SYMBOLIC:
            symbolic_indicators = [
                "hands", "feet", "eyes", "elderly", " sage ", "artisan", "craftsman",
                "figure", "silhouette",
            ]
            found_symbolic = any(
                re.search(r"\b" + re.escape(ind) + r"\b", prompt_lower)
                for ind in symbolic_indicators
            )
            if not found_symbolic:
                errors.append(
                    ValidationError(
                        code="HUMAN_CLASSIFICATION_VIOLATED",
                        message="Symbolic human expected but none detected in prompt.",
                        severity="critical",
                        hint="Include a symbolic human figure matching the narration.",
                    )
                )
        elif human_classification == HumanClassification.HUMAN_REQUIRED:
            if not any(
                ind in prompt_lower
                for ind in [
                    "man", "woman", "person", "people", "child", "face", "figure", "body"
                ]
            ):
                errors.append(
                    ValidationError(
                        code="HUMAN_CLASSIFICATION_VIOLATED",
                        message="Human figure required but none detected in prompt.",
                        severity="critical",
                        hint="Add a human subject matching Scene Analysis.",
                    )
                )
        elif human_classification == HumanClassification.NAMED_PERSON_REQUIRED:
            named_person = scene_analysis.get("named_person", "")
            if named_person and named_person.lower() not in prompt_lower:
                errors.append(
                    ValidationError(
                        code="NAMED_PERSON_MISSING",
                        message=f"Named person '{named_person}' is missing from the prompt.",
                        severity="critical",
                        allowed_values=[named_person],
                        hint="The named person from Scene Analysis must appear.",
                    )
                )

        passed = len(errors) == 0
        return ValidationResult(passed=passed, errors=errors)


# ── Symbolism Validator ────────────────────────────────────────────────────────


class SymbolismValidator:
    """Prevent symbolic replacement of the literal story.

    Example:
      Narration: "The mother eagle encourages the chick."
      Reject: old man, weathered hand, candle, symbolic traveller
      Accept: mother eagle encouraging the chick
    """

    _SYMBOLIC_REPLACEMENTS: tuple[str, ...] = (
        "old man",
        "weathered hand",
        "candle",
        "symbolic traveller",
        "symbolic traveler",
        "lone figure",
        "mysterious stranger",
        "wise elder",
        "ancient sage",
        " faceless ",
        "silhouette of a",
        "shadowy figure",
        "ethereal being",
        "spirit guide",
        "guardian",
        "mentor",
        "guru",
        "teacher",
        "master",
    )

    def validate(self, narration: str, prompt: str) -> ValidationResult:
        errors: list[ValidationError] = []
        prompt_lower = prompt.lower()

        # Extract key nouns from narration (simple heuristic: words > 3 chars)
        narration_keywords = set(re.findall(r"\b[a-z]{4,}\b", narration.lower()))

        # Check for symbolic replacements that don't appear in narration
        narration_lower = narration.lower()
        for symbol in self._SYMBOLIC_REPLACEMENTS:
            if symbol in prompt_lower:
                # If the symbolic term appears in narration, it's OK
                if symbol not in narration_lower:
                    errors.append(
                        ValidationError(
                            code="SYMBOLIC_REPLACEMENT",
                            message=f"Symbolic replacement detected: '{symbol}'.",
                            severity="critical",
                            hint="Symbolism may enhance but must never replace the literal story.",
                        )
                    )
                    break

        passed = len(errors) == 0
        return ValidationResult(passed=passed, errors=errors)


# ── Realism Validator ──────────────────────────────────────────────────────────


class RealismValidator:
    """Validate realistic scale, proportions, anatomy, architecture, objects, birds, camera."""

    _UNREALISTIC_PATTERNS: tuple[str, ...] = (
        "giant",
        "colossal",
        "tiny person",
        "microscopic",
        "gigantic",
        " oversized",
        "distorted proportions",
        "melting",
        "floating",
        "shattered",
        "broken chains",
        "fractal universe",
        "cosmic portal",
        "ethereal glow",
        "glowing chakras",
        "third eye beam",
        "multiple heads",
        "extra limbs",
        "disembodied",
        "floating clocks",
        "cracked desert merging with sky",
    )

    _REALISTIC_BIRD_TERMS: tuple[str, ...] = (
        "eagle",
        "hawk",
        "falcon",
        "owl",
        "sparrow",
        "crow",
        "raven",
        "pigeon",
        "parrot",
        "vulture",
        "kite",
        "harrier",
        "buzzard",
        "kestrel",
        "condor",
        "albatross",
    )

    def validate(self, prompt: str) -> ValidationResult:
        errors: list[ValidationError] = []
        prompt_lower = prompt.lower()

        # Unrealistic proportions / anatomy / objects
        for pattern in self._UNREALISTIC_PATTERNS:
            if pattern in prompt_lower:
                errors.append(
                    ValidationError(
                        code="UNREALISTIC_PROPORTIONS",
                        message=f"Unrealistic element detected: '{pattern.strip()}'.",
                        severity="minor",
                        hint="Use realistic scale, proportions, and anatomy.",
                    )
                )
                break

        # Realistic bird sizes (if bird is mentioned)
        has_bird = any(bird in prompt_lower for bird in self._REALISTIC_BIRD_TERMS)
        if has_bird:
            giant_terms = ["giant eagle", "colossal eagle", "huge eagle", "enormous eagle"]
            if any(term in prompt_lower for term in giant_terms):
                errors.append(
                    ValidationError(
                        code="UNREALISTIC_BIRD_SIZE",
                        message="Bird size described unrealistically large.",
                        severity="minor",
                        hint="Use realistic bird proportions.",
                    )
                )

        # Camera perspective realism
        impossible_perspectives = [
            "camera inside the bird",
            "camera inside the eagle",
            "view from inside the",
            "flying through the",
        ]
        for impossible in impossible_perspectives:
            if impossible in prompt_lower:
                errors.append(
                    ValidationError(
                        code="UNREALISTIC_PERSPECTIVE",
                        message=f"Impossible camera perspective: '{impossible}'.",
                        severity="minor",
                        hint="Use believable external camera angles.",
                    )
                )
                break

        passed = len(errors) == 0
        return ValidationResult(passed=passed, errors=errors)


# ── Feedback composition ───────────────────────────────────────────────────────


def compose_feedback(result: ValidationResult) -> str:
    """Build the structured retry feedback block from a ValidationResult."""
    return result.feedback_text


def run_validators(
    scene_analysis: dict,
    prompt: str,
    narration: str,
    human_classification: HumanClassification | None = None,
    scene_category: str = "",
    visual_anchor: str = "",
) -> ValidationResult:
    """Run all story-fidelity validators and return the combined result."""
    fidelity = StoryFidelityValidator().validate(
        scene_analysis, prompt, narration, human_classification,
        scene_category, visual_anchor,
    )
    symbolism = SymbolismValidator().validate(narration, prompt)
    realism = RealismValidator().validate(prompt)

    all_errors = fidelity.errors + symbolism.errors + realism.errors
    passed = fidelity.passed and symbolism.passed and realism.passed
    return ValidationResult(passed=passed, errors=all_errors)


RETRY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "scene_id": {"type": "integer"},
        "visual_prompt": {"type": "string", "minLength": 50},
        "changes_made": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "violation_addressed": {"type": "string"},
    },
    "required": ["scene_id", "visual_prompt", "changes_made", "violation_addressed"],
    "additionalProperties": False,
}


def parse_retry_response(raw: str, expected_scene_id: int) -> dict | None:
    """Parse LLM retry response. Handles: raw JSON, markdown-fenced JSON,
    leading/trailing whitespace, embedded JSON. Returns None on failure
    with detailed logging.
    """
    if not raw or not raw.strip():
        logger.error("Scene {} | retry response is empty", expected_scene_id)
        return None

    text = raw.strip()

    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    fence_match = re.search(fence_pattern, text)
    if fence_match:
        text = fence_match.group(1).strip()
        logger.debug("Scene {} | stripped markdown fence from response", expected_scene_id)

    if not text.startswith("{"):
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            text = text[json_start:json_end]
            logger.debug("Scene {} | extracted JSON object from response", expected_scene_id)
        else:
            logger.error(
                "Scene {} | retry response contains no JSON object\n"
                "Raw response (first 500 chars):\n{}",
                expected_scene_id,
                raw[:500],
            )
            return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(
            "Scene {} | JSONDecodeError: {} "
            "at line {}, column {} (char {})\n"
            "Problematic section:\n{}",
            expected_scene_id,
            e.msg,
            e.lineno,
            e.colno,
            e.pos,
            text[max(0, e.pos - 50): e.pos + 50],
        )
        return None

    required_fields = ["scene_id", "visual_prompt", "changes_made", "violation_addressed"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        logger.error(
            "Scene {} | schema missing fields: {}\nGot keys: {}",
            expected_scene_id,
            missing,
            list(data.keys()),
        )
        return None

    if data["scene_id"] != expected_scene_id:
        logger.error(
            "Scene {} | scene_id mismatch: expected {}, got {}",
            expected_scene_id,
            expected_scene_id,
            data["scene_id"],
        )
        return None

    if not data["visual_prompt"] or len(data["visual_prompt"].strip()) < 50:
        logger.error(
            "Scene {} | visual_prompt is empty or too short: '{}'",
            expected_scene_id,
            data["visual_prompt"][:100],
        )
        return None

    if not isinstance(data["changes_made"], list) or len(data["changes_made"]) == 0:
        logger.error("Scene {} | changes_made is empty or not a list", expected_scene_id)
        return None

    return data


def build_retry_prompt(
    scene: dict,
    scene_analysis: dict,
    narration: str,
    violation_feedback: str,
    style: str | None = None,
    entity_constraints_section: str = "",
    scene_analysis_section: str = "",
    human_classification: HumanClassification | None = None,
) -> str:
    """Build a strict-JSON retry prompt for a single scene."""
    # Hard constraints pinned at top of the retry block so the model reads them
    # as rules before anything else.  The human_classification rule is expanded
    # to plain English so the model knows e.g. that "hands" count as human under
    # NO_HUMAN_ALLOWED.
    hc_value = (
        human_classification.value
        if human_classification is not None
        else scene_analysis.get("human_requirement", "forbidden")
    )
    human_rule = (
        HUMAN_CLASSIFICATION_RULES.get(human_classification, "")
        if human_classification is not None
        else ""
    )
    allowed_chars = (
        scene_analysis.get("allowed_characters") or scene_analysis.get("scene_characters") or []
    )
    allowed_chars_str = (
        ", ".join(allowed_chars)
        if allowed_chars
        else "NONE — introduce no named person or figure"
    )
    environment = scene_analysis.get("environment", "")
    env_str = environment if environment else "unspecified"

    retry_block = f"""\
FAILED — REGENERATE THIS SCENE ONLY

SCENE ID: {scene.get('index')}
NARRATION: {narration}

HARD CONSTRAINTS (non-negotiable):
  Characters: ONLY {allowed_chars_str}
  Environment: MUST be one of [{env_str}]; no substitution.
  human_classification={hc_value}: {human_rule}

VIOLATION TO FIX:
{violation_feedback}

ORIGINAL PROMPT (contains violation):
{scene.get('visual_prompt', '')}

REQUIRED CHANGES:
- Fix every violation listed above.
- Keep the same cinematic quality, shot type, mood, and era.
- Introduce no new violations.

Return ONLY valid JSON matching this exact structure. No explanation, no markdown,
no code fences, no preamble, no apology. Begin your response with {{ and end with }}.

{{
  "scene_id": {scene.get('index')},
  "visual_prompt": "your rewritten prompt here",
  "changes_made": ["change 1", "change 2"],
  "violation_addressed": "brief description of what you fixed"
}}"""
    base_prompt = build_visual_prompts_prompt(
        [scene],
        style,
        prev_context=None,
        entity_constraints_section=entity_constraints_section,
        scene_analysis_section=scene_analysis_section,
    )
    return f"{base_prompt}\n\n{retry_block}"


class RetryCoordinator:
    """Coordinate targeted regeneration of failed scenes only.

    Given a failed scene's ValidationResult and its Scene Analysis / narration,
    construct a structured retry request that instructs the LLM to regenerate
    ONLY that single scene while preserving the original story intent.
    """

    @staticmethod
    def build_retry_request(
        scene_index: int,
        scene_analysis: dict,
        narration: str,
        validation_result: ValidationResult,
    ) -> str:
        allowed = scene_analysis.get("allowed_characters", []) or scene_analysis.get("scene_characters", [])
        primary_action = scene_analysis.get("primary_action", "")
        blocks: list[str] = [
            "FAILED",
            "",
            "Reason:",
        ]
        for err in validation_result.errors:
            blocks.append(f"  - {err.code}: {err.message}")
        blocks.append("")
        if allowed:
            blocks.append("Allowed:")
            for value in allowed:
                blocks.append(f"  - {value}")
            blocks.append("")
        if primary_action:
            blocks.append(f"Primary Action:\n  {primary_action}\n")
        blocks.append("Please regenerate while preserving Story Analysis and Narration.")
        blocks.append("Return ONLY corrected JSON for this scene.")
        return "\n".join(blocks)

    @staticmethod
    def scene_needs_retry(validation_result: ValidationResult) -> bool:
        return not validation_result.passed
