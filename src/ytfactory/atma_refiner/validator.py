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

from ytfactory.agents.prompts.branding import CLOSING_VARIATIONS, SOFT_CTA
from ytfactory.domain.script_revision import (
    BeatEvidence,
    EngagementElement,
    EngagementType,
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
            # Action-first / scene-first openings (preferred by the current refiner)
            re.compile(
                r"\b(?:he|she|they|the (?:man|woman|person|craftsman|warrior|leader|"
                r"teacher|student|monk|soldier|artist|master))\s+"
                r"(?:had|was|were|stood|sat|walked|looked|knew|carried|held|built|"
                r"faced|spent|worked|woke|opened|entered|left|returned|watched|waited)\b",
                re.IGNORECASE,
            ),
            re.compile(
                r"\b(?:for (?:years|decades|months|generations)|"
                r"every (?:morning|day|night|week)|"
                r"day after day|year after year|"
                r"one (?:morning|day|evening|night)|"
                r"it (?:started|began)|"
                r"a (?:man|woman|person|craftsman|warrior|teacher|student|child) (?:who|whose|that))\b",
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
            # Documentary-style and broader application language
            re.compile(
                r"\b(?:in (?:daily )?(?:life|practice)|"
                r"for (?:anyone|most people|someone) (?:who|that|in)|"
                r"for (?:anyone|most people)|"
                r"this (?:applies|translates|shows up)|"
                r"bring this|take this into|"
                r"we (?:often|tend to)|"
                r"in (?:a meeting|a (?:relationship|conversation|team)|an office)|"
                r"anyone (?:who|in)|most people (?:who|in|face)|"
                r"this (?:changes|shifts) how)\b",
                re.IGNORECASE,
            ),
            # Conditional instructional APPLY ("If you are...", "If your goal...", "becomes practical")
            re.compile(
                r"\b(?:if you (?:are|want|have|need|feel)|"
                r"if your (?:goal|aim|dream|purpose|practice)|"
                r"becomes practical)\b",
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


# ── Engagement element detection ──────────────────────────────────────────────

# Marker injected by the LLM for dedicated-scene identification
_ENGAGEMENT_MARKER_RE = re.compile(
    r"\[ENGAGEMENT:\s*(value_promise|journey_invitation|comment_prompt|"
    r"subscribe_promise|branding_end)\]",
    re.IGNORECASE,
)

# Deterministic BRANDING_END: brand config closing phrases (same source as
# scene_planner._CLOSING_TRIGGERS — no regex heuristics needed here).
_BRAND_CLOSING_PHRASES: frozenset[str] = frozenset(
    phrase.lower().strip().rstrip(".")
    for phrase in CLOSING_VARIATIONS + [SOFT_CTA]
    if phrase
)

# Fallback content patterns — only used when the LLM omits the [ENGAGEMENT:] marker.
_VALUE_PROMISE_RE = re.compile(
    r"\b(by the end of this|by the time (?:we|you)|"
    r"you'?ll (?:understand|discover|see|know|learn|realize)|"
    r"in (?:the )?next (?:few )?minutes|what you'?ll (?:take away|gain|walk away))\b",
    re.IGNORECASE,
)
_JOURNEY_INVITATION_RE = re.compile(
    r"\b(every week|one ancient idea|join us on this journey|"
    r"atma theory (?:is|brings|offers)|(?:this is |this becomes )?our journey|"
    r"(?:join|walk with) us)\b",
    re.IGNORECASE,
)
_COMMENT_PROMPT_RE = re.compile(
    r"\b(tell me (?:below|in the comments?)|"
    r"leave (?:your|a) (?:answer|response|thought) (?:below|in the comments?)|"
    r"(?:which|what) (?:of these|do you)|"
    r"(?:let me know|share) (?:below|in the comments?))\b",
    re.IGNORECASE,
)
_SUBSCRIBE_PROMISE_RE = re.compile(
    r"\b(subscribe (?:so|and|to)|"
    r"if this (?:resonated?|landed|spoke|moved)|"
    r"(?:hit|press|click) (?:subscribe|the subscribe))\b",
    re.IGNORECASE,
)
# BRANDING_END regex fallback — fires only when neither the marker nor the brand
# config phrase matches (e.g. a legacy script with custom closing language).
_BRANDING_END_FALLBACK_RE = re.compile(
    r"\b(this is atma theory|until (?:next time|we meet again))\b",
    re.IGNORECASE,
)


def _closing_paragraph_matches_brand(script_text: str) -> str:
    """Return the closing paragraph text if it contains a brand closing phrase."""
    paras = [p.strip() for p in re.split(r"\n\n+", script_text) if p.strip()]
    if not paras:
        return ""
    closing = _strip_visual_directions(paras[-1]).lower().strip().rstrip(".")
    for phrase in _BRAND_CLOSING_PHRASES:
        if phrase in closing:
            return paras[-1]
    return ""


def _detect_engagement_elements(script_text: str) -> list[EngagementElement]:
    """Detect engagement elements in the refined script.

    Primary path: explicit [ENGAGEMENT: <type>] marker (fallback_derived=False).
    Fallback path: content-pattern matching for elements the LLM left unmarked
    (fallback_derived=True). ENGAGEMENT_MISSING is only emitted when neither
    path finds the element.

    BRANDING_END uses the brand config closing phrases as the deterministic
    fallback before the regex pattern, matching scene_planner._CLOSING_TRIGGERS.
    """
    elements: list[EngagementElement] = []
    found_types: set[EngagementType] = set()

    # ── Marker-based detection (primary, fallback_derived=False) ─────────────
    for m in _ENGAGEMENT_MARKER_RE.finditer(script_text):
        raw_type = m.group(1).lower()
        try:
            etype = EngagementType(raw_type)
        except ValueError:
            continue
        if etype in found_types:
            continue
        start = max(0, m.start() - 20)
        snippet = script_text[start : m.end() + 300].strip()[:300]
        elements.append(
            EngagementElement(
                engagement_type=etype,
                text_snippet=snippet,
                is_dedicated_scene=(etype == EngagementType.JOURNEY_INVITATION),
                is_final_scene=(etype == EngagementType.BRANDING_END),
                fallback_derived=False,
            )
        )
        found_types.add(etype)

    # ── Fallback detection for unmarked elements (fallback_derived=True) ─────
    spoken = _strip_visual_directions(script_text)

    # BRANDING_END: deterministic brand-config check first, regex only if needed
    if EngagementType.BRANDING_END not in found_types:
        closing_para = _closing_paragraph_matches_brand(script_text)
        if closing_para:
            elements.append(
                EngagementElement(
                    engagement_type=EngagementType.BRANDING_END,
                    text_snippet=closing_para[:300],
                    is_dedicated_scene=False,
                    is_final_scene=True,
                    fallback_derived=True,
                )
            )
            found_types.add(EngagementType.BRANDING_END)
        else:
            match = _BRANDING_END_FALLBACK_RE.search(spoken)
            if match:
                snippet = spoken[max(0, match.start() - 20) : match.end() + 200].strip()[:300]
                elements.append(
                    EngagementElement(
                        engagement_type=EngagementType.BRANDING_END,
                        text_snippet=snippet,
                        is_dedicated_scene=False,
                        is_final_scene=True,
                        fallback_derived=True,
                    )
                )
                found_types.add(EngagementType.BRANDING_END)

    fallback_checks = [
        (EngagementType.VALUE_PROMISE, _VALUE_PROMISE_RE),
        (EngagementType.JOURNEY_INVITATION, _JOURNEY_INVITATION_RE),
        (EngagementType.COMMENT_PROMPT, _COMMENT_PROMPT_RE),
        (EngagementType.SUBSCRIBE_PROMISE, _SUBSCRIBE_PROMISE_RE),
    ]
    for etype, pattern in fallback_checks:
        if etype in found_types:
            continue
        match = pattern.search(spoken)
        if match:
            snippet = spoken[max(0, match.start() - 20) : match.end() + 200].strip()[:300]
            elements.append(
                EngagementElement(
                    engagement_type=etype,
                    text_snippet=snippet,
                    is_dedicated_scene=(etype == EngagementType.JOURNEY_INVITATION),
                    is_final_scene=False,
                    fallback_derived=True,
                )
            )
            found_types.add(etype)

    return elements


def _strip_visual_directions(text: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", text)


def _strip_engagement_blocks(text: str) -> str:
    """Remove [ENGAGEMENT: ...] paragraphs and their content from text.

    Handles both formats produced by the LLM:

      Format A — marker in its own paragraph, content in the next:
          [ENGAGEMENT: value_promise]

          Content paragraph here.

      Format B — marker and content share a paragraph (no blank line):
          [ENGAGEMENT: value_promise]
          Content text here.

    In Format A the marker paragraph AND the immediately following content
    paragraph are both excluded. In Format B the combined paragraph is excluded
    and no additional paragraph is consumed.

    [NARRATIVE_ENDING] and the content that follows it are preserved.
    Adjacent engagement markers are each handled independently — a lone marker
    never consumes another marker as its content paragraph.
    """
    paragraphs = re.split(r"\n\n+", text)
    result: list[str] = []
    skip_next_para = False

    for para in paragraphs:
        lines = [ln for ln in para.splitlines() if ln.strip()]
        is_engagement = bool(lines) and bool(_ENGAGEMENT_MARKER_RE.match(lines[0].strip()))

        if is_engagement:
            # Skip this paragraph regardless of format.
            # Format A (marker only, len==1) → also skip the next content paragraph.
            # Format B (marker + content, len>1) → nothing extra to skip.
            skip_next_para = len(lines) == 1
            continue

        if skip_next_para:
            # Content paragraph following a lone Format-A marker.
            skip_next_para = False
            continue

        result.append(para)

    return "\n\n".join(result)


def _count_spoken_words(script_text: str) -> int:
    spoken = _strip_visual_directions(script_text)
    return len(spoken.split())


def _check_beat_coverage(script_text: str) -> dict[str, bool]:
    """Regex-based beat coverage check (fallback when no semantic evidence)."""
    narrative_only = _strip_engagement_blocks(script_text)
    spoken_lower = _strip_visual_directions(narrative_only).lower()
    coverage: dict[str, bool] = {}
    for beat_name, patterns in _BEAT_PATTERNS:
        found = any(p.search(spoken_lower) for p in patterns)
        coverage[beat_name] = found
    return coverage


def _check_beat_coverage_with_evidence(
    refined_script: str,
    beat_evidence: dict,  # dict[str, BeatEvidence]
) -> dict[str, bool]:
    """Beat coverage check using LLM semantic evidence where available.

    For each beat:
      Semantic path (evidence present for that beat):
        1. evidence.present must be True
        2. evidence.evidence must be non-empty
        3. The exact evidence text must appear in the narrative-only script
           (engagement blocks stripped so CTA text cannot satisfy any beat)
      Regex fallback (no evidence entry for that beat):
        Falls back to _check_beat_coverage patterns for that beat only.
    """
    # For evidence verification: engagement stripped, visual directions kept
    # (LLM may quote text near visual cue markers; that is acceptable)
    narrative_only = _strip_engagement_blocks(refined_script)
    # For regex fallback on partial-evidence dicts
    spoken_lower = _strip_visual_directions(narrative_only).lower()

    coverage: dict[str, bool] = {}
    for beat_name, patterns in _BEAT_PATTERNS:
        ev: BeatEvidence | None = beat_evidence.get(beat_name)
        if ev is not None:
            # Semantic path
            if ev.present and ev.evidence.strip():
                coverage[beat_name] = ev.evidence in narrative_only
            else:
                coverage[beat_name] = False
        else:
            # Regex fallback for this beat
            coverage[beat_name] = any(p.search(spoken_lower) for p in patterns)

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
        beat_evidence: dict | None = None,  # dict[str, BeatEvidence] | None
    ) -> ScriptValidationResult:
        """Validate a 7-Beat refined script.

        Args:
            refined_script: The refined narration script.
            identity: ScriptIdentity extracted before refinement.
            base_script: Original source script for factual-risk comparison.
            beat_evidence: LLM-provided semantic evidence dict
                (``{beat_name: BeatEvidence}``).  When non-empty, semantic
                verification is the primary path; regex is used as fallback
                for any beat missing from the dict.  When None or empty, the
                regex-only path is used (backward-compatible with old scripts).
        """
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
        # Primary: semantic evidence from the LLM (engagement content excluded).
        # Fallback: regex patterns when no evidence is provided.
        if beat_evidence:
            beat_coverage = _check_beat_coverage_with_evidence(refined_script, beat_evidence)
        else:
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

        # ── Engagement layer detection ────────────────────────────────────────
        engagement_elements = _detect_engagement_elements(refined_script)
        found_types = {e.engagement_type for e in engagement_elements}
        required = [
            EngagementType.VALUE_PROMISE,
            EngagementType.JOURNEY_INVITATION,
            EngagementType.COMMENT_PROMPT,
            EngagementType.SUBSCRIBE_PROMISE,
            EngagementType.BRANDING_END,
        ]
        for etype in required:
            if etype not in found_types:
                flags.append(
                    ValidationFlag(
                        flag_type=ValidationFlagType.ENGAGEMENT_MISSING,
                        location=etype.value,
                        message=(
                            f"Engagement element {etype.value!r} not detected. "
                            "Add the [ENGAGEMENT: "
                            + etype.value
                            + "] marker or matching content."
                        ),
                        severity="warning",
                        auto_fixable=False,
                    )
                )

        status = "REVIEW_REQUIRED" if flags else "PASS"
        return ScriptValidationResult(
            status=status,
            spoken_word_count=spoken_wc,
            beat_coverage=beat_coverage,
            flags=flags,
            engagement_elements=engagement_elements,
            beat_evidence=beat_evidence or {},
        )
