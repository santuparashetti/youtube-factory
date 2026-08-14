"""ScriptValidator — pre-review validation of the 7-Beat refined script.

Validates:
  1. Spoken word count (600-750)
  2. Seven-beat coverage (heuristic pattern match)
  3. ScriptIdentity preservation (key thesis / topic phrases still present)
  4. Factual risk (new years/names not in the source)
  5. Narrative coherence (opening and closing present)

Safe auto-fix:
  - Trailing whitespace / encoding issues (handled upstream, not here)
  - Nothing else — auto-fixing content is out of scope for the validator;
    human judgment is required for any content issue.

Validation failure behavior:
  - Issues that can be safely corrected automatically are flagged auto_fixable=True.
  - All other issues are REVIEW_REQUIRED: the script is preserved, the flags are
    attached, and the reviewer sees them at human review.
"""

from __future__ import annotations

import re

from ytfactory.domain.script_revision import (
    ScriptIdentity,
    ScriptValidationResult,
    ValidationFlag,
    ValidationFlagType,
)

# ── Word-count targets (spoken words only) ────────────────────────────────────
_WORD_COUNT_MIN = 600
_WORD_COUNT_MAX = 750

# ── Beat coverage patterns ─────────────────────────────────────────────────────
# Each tuple: (beat_name, list of regex patterns that signal the beat is present)
_BEAT_PATTERNS: list[tuple[str, list[re.Pattern]]] = [
    (
        "DISRUPT",
        [
            re.compile(
                r"\b(imagine|picture this|consider|what if|there (?:is|was|were)|"
                r"have you ever|the moment|once there was|it was|"
                r"in \d{4}|standing alone|alone at|at the edge)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "CHALLENGE",
        [
            re.compile(
                r"\b(most (?:people|of us)|we (?:think|believe|assume|tell ourselves)|"
                r"but what if|that'?s not|conventional wisdom|"
                r"the usual (?:answer|assumption|belief)|but here'?s)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "PROVE",
        [
            re.compile(
                r"\b((?:a|the) (?:study|research|experiment|example|story of|case of)|"
                r"in \d{4}|(?:he|she|they) (?:discovered|found|proved|showed|realized)|"
                r"history (?:of|shows|tells)|look at|consider|take|examine)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "REVEAL",
        [
            re.compile(
                r"\b(the (?:real|deeper|true) (?:problem|question|issue|lesson|shift|insight)|"
                r"(?:it|this) is not about|the shift is|what changes is|"
                r"the insight is|the difference is|what this means|"
                r"not (?:what|how) .{1,30} but)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "FRAME",
        [
            re.compile(
                # "First," / "Firstly:" / "Second," / "Secondly:" / "Third:" etc.
                # No trailing \b — these end with punctuation (non-word chars).
                r"\b(?:first|second|third)(?:ly)?[,:\-]",
                re.IGNORECASE,
            ),
            re.compile(
                # "Three principles" / "3 practices" / "three rules" etc.
                # "Principle one/two/three" / "Rule 1/2/3"
                r"\b(?:"
                r"(?:three|3)\s+(?:principles|practices|rules|shifts|questions|steps|"
                r"things|ways|truths|keys|insights|habits|pillars|lessons|ideas)|"
                r"(?:rule|principle|practice|shift|step|question)\s+(?:one|two|three|1|2|3)"
                r")\b",
                re.IGNORECASE,
            ),
            re.compile(
                # "First rule" / "The second principle" / "Third secret" etc.
                # Ordinal + framework noun — the pattern that was missing from the log.
                r"\b(?:the\s+)?(?:first|second|third)\s+"
                r"(?:rule|principle|practice|shift|step|truth|insight|key|"
                r"lesson|pillar|secret|concept|element|teaching|thing|idea|way|skill)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "APPLY",
        [
            re.compile(
                r"\b(in your (?:own )?(?:life|work|day|relationships?)|"
                r"the next time|when you|every time you|"
                r"at (?:work|home|the office)|with your (?:family|team|colleagues)|"
                r"in your (?:career|marriage|parenting)|apply this)\b",
                re.IGNORECASE,
            ),
        ],
    ),
    (
        "TRANSFORM",
        [
            re.compile(
                r"\b(stop (?:being|trying|seeking|chasing|measuring)|start (?:being|building|living|treating)|"
                r"this is (?:atma theory|the (?:path|way|invitation|journey|practice))|"
                r"(?:subscribe|join us|if (?:this|these ideas?) (?:resonated?|spoke|moved))|"
                r"(?:you are|we are) (?:not|more than)|"
                r"the (?:real|true) (?:measure|metric|test|question|work))\b",
                re.IGNORECASE,
            ),
        ],
    ),
]


def _strip_visual_directions(text: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", text)


def _count_spoken_words(script_text: str) -> int:
    spoken = _strip_visual_directions(script_text)
    return len(spoken.split())


def _check_beat_coverage(script_text: str) -> dict[str, bool]:
    spoken_lower = _strip_visual_directions(script_text).lower()
    coverage: dict[str, bool] = {}
    for beat_name, patterns in _BEAT_PATTERNS:
        found = any(p.search(spoken_lower) for p in patterns)
        coverage[beat_name] = found
    return coverage


def _check_identity_preservation(
    script_text: str,
    identity: ScriptIdentity,
) -> list[ValidationFlag]:
    flags: list[ValidationFlag] = []
    spoken = _strip_visual_directions(script_text).lower()

    # Check core topic is still referenced
    if identity.core_topic:
        topic_words = [w for w in identity.core_topic.lower().split() if len(w) > 4]
        if topic_words:
            found = sum(1 for w in topic_words if w in spoken)
            if found == 0:
                flags.append(
                    ValidationFlag(
                        flag_type=ValidationFlagType.IDENTITY_DRIFT,
                        location="full_script",
                        message=f"Core topic '{identity.core_topic}' appears to have drifted — "
                        "none of its key words are present in the refined script.",
                        severity="warning",
                        auto_fixable=False,
                    )
                )

    # Check key thesis phrase is approximately preserved
    if identity.core_thesis:
        thesis_words = [w for w in identity.core_thesis.lower().split() if len(w) > 4]
        if thesis_words:
            found = sum(1 for w in thesis_words if w in spoken)
            coverage = found / len(thesis_words)
            if coverage < 0.4:
                flags.append(
                    ValidationFlag(
                        flag_type=ValidationFlagType.THESIS_DRIFT,
                        location="full_script",
                        message="Core thesis has substantially drifted. "
                        f"Only {found}/{len(thesis_words)} key thesis words found.",
                        severity="warning",
                        auto_fixable=False,
                    )
                )

    return flags


def _check_factual_risks(
    script_text: str,
    base_script: str,
) -> list[ValidationFlag]:
    flags: list[ValidationFlag] = []
    spoken = _strip_visual_directions(script_text)
    source_spoken = _strip_visual_directions(base_script)

    year_re = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9])\b")
    source_years = set(year_re.findall(source_spoken))
    refined_years = set(year_re.findall(spoken))
    new_years = refined_years - source_years
    if new_years:
        flags.append(
            ValidationFlag(
                flag_type=ValidationFlagType.FACTUAL_RISK,
                location="full_script",
                message=f"Years not present in source script: {sorted(new_years)}. "
                "Verify these are not fabricated historical claims.",
                severity="warning",
                auto_fixable=False,
            )
        )

    return flags


class ScriptValidator:
    """Validates a 7-Beat refined script before human review."""

    def validate(
        self,
        refined_script: str,
        identity: ScriptIdentity,
        base_script: str = "",
    ) -> ScriptValidationResult:
        flags: list[ValidationFlag] = []

        # ── Word count ────────────────────────────────────────────────────────
        spoken_wc = _count_spoken_words(refined_script)
        if spoken_wc < _WORD_COUNT_MIN:
            flags.append(
                ValidationFlag(
                    flag_type=ValidationFlagType.WORD_COUNT,
                    location="full_script",
                    message=f"{spoken_wc} spoken words; target is {_WORD_COUNT_MIN}–{_WORD_COUNT_MAX}. "
                    "Script may be too short.",
                    severity="warning",
                    auto_fixable=False,
                )
            )
        elif spoken_wc > _WORD_COUNT_MAX:
            flags.append(
                ValidationFlag(
                    flag_type=ValidationFlagType.WORD_COUNT,
                    location="full_script",
                    message=f"{spoken_wc} spoken words; target is {_WORD_COUNT_MIN}–{_WORD_COUNT_MAX}. "
                    "Script may be too long.",
                    severity="warning",
                    auto_fixable=False,
                )
            )

        # ── Beat coverage ─────────────────────────────────────────────────────
        beat_coverage = _check_beat_coverage(refined_script)
        missing_beats = [name for name, found in beat_coverage.items() if not found]
        for beat_name in missing_beats:
            flags.append(
                ValidationFlag(
                    flag_type=ValidationFlagType.BEAT_COVERAGE,
                    location=beat_name,
                    message=f"Beat {beat_name} may be missing or underdeveloped. "
                    "Check that the script fulfills this narrative function.",
                    severity="warning",
                    auto_fixable=False,
                )
            )

        # ── Identity preservation ─────────────────────────────────────────────
        flags.extend(_check_identity_preservation(refined_script, identity))

        # ── Factual risks ─────────────────────────────────────────────────────
        if base_script:
            flags.extend(_check_factual_risks(refined_script, base_script))

        # ── Narrative coherence (non-empty opening and closing) ───────────────
        paras = [p.strip() for p in re.split(r"\n\n+", refined_script) if p.strip()]
        if len(paras) < 4:
            flags.append(
                ValidationFlag(
                    flag_type=ValidationFlagType.NARRATIVE_COHERENCE,
                    location="full_script",
                    message="Script has fewer than 4 paragraphs. Check for truncation.",
                    severity="error",
                    auto_fixable=False,
                )
            )

        status = "REVIEW_REQUIRED" if flags else "PASS"
        return ScriptValidationResult(
            status=status,
            spoken_word_count=spoken_wc,
            beat_coverage=beat_coverage,
            flags=flags,
        )
