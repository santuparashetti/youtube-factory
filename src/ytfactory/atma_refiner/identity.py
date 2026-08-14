"""Deterministic ScriptIdentity extraction from raw script text.

No LLM calls. Uses heuristic pattern matching to identify the soul of the
script: its thesis, emotional promise, key stories, insights, and facts.

The identity is extracted BEFORE any LLM refinement begins and is passed
as a protected constraint so the editor cannot silently remove what matters.
"""

from __future__ import annotations

import re

from ytfactory.domain.script_revision import ScriptIdentity

# ── Thesis / claim detection ──────────────────────────────────────────────────
_THESIS_PATTERNS = [
    re.compile(
        r"(?:not about|isn't about|is not about|is about|the truth is|the answer is|"
        r"what this means is|the real (?:lesson|question|secret|problem|reason)|"
        r"the deeper (?:truth|lesson|question|meaning|insight)|"
        r"the secret (?:of|to)|what separates|the difference between|"
        r"it(?:'s| is) not .{5,60}but\b|"
        r"(?:success|greatness|mastery|wisdom|growth|power|strength|freedom|focus|"
        r"consistency|discipline|character|patience)\s+(?:is|comes from|requires|means))\s*"
        r"[^.!?]{10,140}[.!?]",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:we realize|we understand|the key insight|at its core|in essence|"
        r"fundamentally|what matters most|the principle is|the lesson is|"
        r"this is what|this is why|this means that)\s+[^.!?]{10,120}[.!?]",
        re.IGNORECASE,
    ),
    # "You don't need X. You just need Y." style payoff sentences
    re.compile(
        r"you (?:don't|do not) need .{5,60}\.\s+you (?:just |only )?need [^.!?]{5,80}[.!?]",
        re.IGNORECASE,
    ),
]

# ── Generalizable-sentence signals (for thesis fallback scoring) ──────────────
_UNIVERSAL_SIGNAL_RE = re.compile(
    r"\b(?:you|we|your|our|everyone|anyone|people|"
    r"consistency|focus|mastery|greatness|success|growth|wisdom|"
    r"principle|practice|habit|effort|discipline|character|patience|"
    r"relentless|unbroken|continuous|persistent)\b",
    re.IGNORECASE,
)
_NARRATIVE_VERB_RE = re.compile(
    r"\b(?:walked|ran|stood|sat|said|asked|replied|looked|felt|thought|knew|"
    r"realized|discovered|found|saw|heard|lived|died|traveled|came|went|took|"
    r"gave|left|arrived|began|ended|told|showed|proved|decided|chose)\b",
    re.IGNORECASE,
)

# ── Emotional promise (hook / first-paragraph emotional language) ─────────────
_EMOTION_WORDS = re.compile(
    r"\b(imagine|what if|consider|have you ever|the feeling|the moment|the day|"
    r"story of|story about|once there was|there was a|lived a|faced with|"
    r"struggled|feared|longed|searched|wondered|discovered)\b",
    re.IGNORECASE,
)

# ── Contrast / conflict language ──────────────────────────────────────────────
_CONFLICT_PATTERNS = re.compile(
    r"(?:but instead|instead of|rather than|despite|even though|although|however,|"
    r"yet (?:he|she|they|we)|most (?:people|of us)|we (?:think|believe|assume))[^.!?]{10,150}[.!?]",
    re.IGNORECASE,
)

# ── Philosophical insight markers ─────────────────────────────────────────────
_PHILOSOPHY_PATTERNS = re.compile(
    r"(?:wisdom|consciousness|awareness|presence|meaning|purpose|freedom|clarity|"
    r"true (?:wealth|success|freedom|wisdom|happiness)|the nature of|"
    r"what it means to be|the source of|this is the path|the way of)\b[^.!?]{5,150}[.!?]",
    re.IGNORECASE,
)

# ── Factual detail patterns: proper nouns, dates, numbers ─────────────────────
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9])\b")
_PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,2}\b")
_STATISTIC_RE = re.compile(
    r"\b\d+(?:\.\d+)?(?:%|percent|times|years|decades|centuries|hours|days)\b",
    re.IGNORECASE,
)

# ── Visual direction (bracketed stage directions) ─────────────────────────────
_VISUAL_RE = re.compile(r"\[([^\]]{5,120})\]")

# ── Metaphor / original idea patterns ────────────────────────────────────────
_METAPHOR_RE = re.compile(
    r"(?:like (?:a|an|the)\s+[A-Za-z ]{3,40}(?:,|\.)|"
    r"as if\s+[^.!?]{5,80}[.!?]|"
    r"(?:is|are|was|were)\s+(?:not (?:just|merely) )?(?:a|an|the)\s+[A-Za-z ]{3,30}[.!?])",
    re.IGNORECASE,
)

# ── Narrative block: past tense storytelling ─────────────────────────────────
_PAST_TENSE_RE = re.compile(
    r"\b(?:walked|ran|stood|sat|said|asked|replied|looked|felt|thought|knew|"
    r"realized|discovered|found|saw|heard|lived|died|traveled|came|went|took|"
    r"gave|left|arrived|began|ended|told|showed|proved|decided|chose)\b",
    re.IGNORECASE,
)


# Preamble patterns: template/meta-description text that precedes the real script
_PREAMBLE_INTRO_RE = re.compile(
    r"^(?:here is|this is|below is|the following is|i(?:'ve| have) (?:created|written|prepared))\b",
    re.IGNORECASE,
)
_PREAMBLE_SEPARATOR_RE = re.compile(r"^-{3,}\s*$")
_PREAMBLE_HEADING_RE = re.compile(r"^#{1,6}\s+")
# Italic-only lines used as section objectives/notes in templates
_PREAMBLE_ITALIC_ONLY_RE = re.compile(r"^\*[^*\n]+\*\s*$")
# Strip markdown formatting to get plain text for key-value detection
_MD_MARKUP_RE = re.compile(r"[*_~`#>\[\]]+")
# Short key: value metadata line (≤ 4 words before the colon, e.g. "Visual Style: ...")
_KV_METADATA_RE = re.compile(r"^([A-Za-z][A-Za-z /]{0,40}):\s+\S")

# Script dialogue labels: "* **Host (On Camera):**" style markers in formatted scripts
_DIALOGUE_LABEL_RE = re.compile(
    r"^\s*[\*\-]\s+\*{0,2}[A-Za-z][^:\n]{0,40}:\*{0,2}\s*",
    re.MULTILINE,
)
# Prose stop-words that should never appear in proper-noun factual details
_PROPER_NOUN_STOPWORDS = frozenset(
    {
        # Common determiners / pronouns that get capitalised mid-quote
        "this", "that", "these", "those", "here", "there", "when", "where", "what",
        "which", "who", "how", "you", "your", "the", "every", "through", "into",
        "about", "with", "from", "just", "will", "have", "been", "they", "their",
        # Script direction labels
        "host", "camera", "voiceover", "visual", "screen", "text", "overlay",
        "scene", "shot", "audio", "music", "fade", "cut", "beat", "intro", "outro",
        "narrator", "speaker", "voice", "background", "foreground",
    }
)


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]


def _strip_dialogue_labels(text: str) -> str:
    """Remove '* **Host (On Camera):**' style labels, leaving only the spoken text."""
    return _DIALOGUE_LABEL_RE.sub("", text).strip()


def _is_preamble(para: str) -> bool:
    """Return True if a paragraph is template metadata, not script narration content."""
    first_line = para.split("\n")[0].strip()
    plain = _MD_MARKUP_RE.sub("", first_line).strip()

    # Hard structural markers
    if _PREAMBLE_SEPARATOR_RE.match(first_line):
        return True
    if _PREAMBLE_HEADING_RE.match(first_line):
        return True

    # Italic-only lines (e.g. *Objective: grab attention*)
    if _PREAMBLE_ITALIC_ONLY_RE.match(first_line) and len(first_line) < 200:
        return True

    # Meta-description opening ("Here is a complete...", "This is a script...")
    if _PREAMBLE_INTRO_RE.match(plain):
        return True

    # Key-value metadata — single-line paragraph whose plain text is "Key: value"
    # with at most 4 words before the colon (e.g. "Estimated Length: 5 min",
    # "Visual Style: Fast-paced B-roll...", "Tone: Inspiring").
    # Multi-line paragraphs are never metadata by this rule.
    if "\n" not in para and _KV_METADATA_RE.match(plain):
        key_words = plain.split(":")[0].strip().split()
        if len(key_words) <= 4:
            return True

    return False


def _strip_preamble(paras: list[str]) -> list[str]:
    """Skip leading paragraphs that are template metadata, not script content."""
    for i, para in enumerate(paras):
        if not _is_preamble(para):
            return paras[i:]
    return paras


def _strip_visual_directions(text: str) -> str:
    return re.sub(r"\[[^\]]*\]", "", text).strip()


def _first_match(patterns, text: str) -> str:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(0).strip()
    return ""


def extract_script_identity(
    script_text: str,
    topic: str = "",
) -> ScriptIdentity:
    """Extract the soul of the script deterministically.

    Runs before any LLM call. Uses heuristic patterns to identify the
    thesis, key story, emotional hook, philosophical insight, factual
    anchors, and visual moments. Returns ScriptIdentity with all
    available fields populated; missing fields default to "".

    The topic argument seeds core_topic when provided (typical: state["topic"]).
    """
    paras = _strip_preamble(_paragraphs(script_text))
    if not paras:
        return ScriptIdentity(core_topic=topic)

    # spoken: no visual directions AND no dialogue labels (for clean pattern matching)
    spoken_raw = "\n\n".join(paras)
    spoken = _strip_dialogue_labels(_strip_visual_directions(spoken_raw))
    opening = paras[0] if paras else ""
    closing = paras[-1] if paras else ""

    # ── Core thesis ───────────────────────────────────────────────────────────
    core_thesis = _first_match(_THESIS_PATTERNS, spoken)
    if not core_thesis:
        # Fallback: scan for a generalizable claim, prioritizing the closing
        # third (where REVEAL/TRANSFORM beats live) over the opening.
        # A generalizable sentence has universal language and no narrative verbs.
        n = len(paras)
        thirds = [
            paras[n * 2 // 3 :],   # closing third — REVEAL / TRANSFORM
            paras[n // 3 : n * 2 // 3],  # middle third — PROVE / FRAME
            paras[: n // 3],        # opening third — last resort
        ]
        for section in thirds:
            for para in section:
                clean = _strip_dialogue_labels(_strip_visual_directions(para))
                for s in re.split(r"(?<=[.!?])\s+", clean):
                    s = s.strip().strip('"\'')
                    if (
                        len(s) > 30
                        and not s.endswith("?")
                        and not _NARRATIVE_VERB_RE.search(s)
                        and _UNIVERSAL_SIGNAL_RE.search(s)
                    ):
                        core_thesis = s
                        break
                if core_thesis:
                    break
            if core_thesis:
                break
        # Last resort: first non-question sentence anywhere (original behavior)
        if not core_thesis:
            for line in spoken.split("\n"):
                line = line.strip()
                for s in re.split(r"(?<=[.!?])\s+", line):
                    s = s.strip()
                    if len(s) > 30 and not s.endswith("?"):
                        core_thesis = s
                        break
                if core_thesis:
                    break

    # ── Emotional promise ─────────────────────────────────────────────────────
    emotional_promise = ""
    for para in paras[:3]:
        if _EMOTION_WORDS.search(para):
            clean_para = _strip_dialogue_labels(_strip_visual_directions(para))
            first_sentences = re.split(r"(?<=[.!?])\s+", clean_para)[:2]
            emotional_promise = " ".join(first_sentences).strip()
            break
    if not emotional_promise:
        emotional_promise = _strip_dialogue_labels(_strip_visual_directions(opening))[:300].strip()

    # ── Central conflict ──────────────────────────────────────────────────────
    conflict_m = _CONFLICT_PATTERNS.search(spoken)
    central_conflict = conflict_m.group(0).strip() if conflict_m else ""

    # ── Key story (longest paragraph with past tense verbs) ──────────────────
    key_story = ""
    best_score = 0
    for para in paras:
        clean_para = _strip_dialogue_labels(_strip_visual_directions(para))
        past_count = len(_PAST_TENSE_RE.findall(clean_para))
        words = len(clean_para.split())
        score = past_count * 10 + (words if past_count > 0 else 0)
        if score > best_score:
            best_score = score
            key_story = clean_para[:500].strip()

    # ── Key philosophical insight ─────────────────────────────────────────────
    phi_m = _PHILOSOPHY_PATTERNS.search(spoken)
    key_philosophical_insight = phi_m.group(0).strip() if phi_m else ""

    # ── Factual details ───────────────────────────────────────────────────────
    important_factual_details: list[str] = []
    years = _YEAR_RE.findall(spoken)
    for y in set(years):
        context_m = re.search(rf".{{0,40}}{y}.{{0,60}}", spoken)
        if context_m:
            important_factual_details.append(context_m.group(0).strip())

    stats = _STATISTIC_RE.findall(spoken)
    for s in set(stats[:5]):
        important_factual_details.append(s)

    # Extract proper nouns from the dialogue-stripped first third (excludes "Host",
    # "Camera" etc. that only appear as script direction labels)
    spoken_first_third = _strip_dialogue_labels(
        _strip_visual_directions("\n\n".join(paras[: max(1, len(paras) // 3)]))
    )
    proper_nouns = list(dict.fromkeys(_PROPER_NOUN_RE.findall(spoken_first_third)))
    for pn in proper_nouns[:10]:
        if pn.lower() not in _PROPER_NOUN_STOPWORDS:
            important_factual_details.append(pn)

    important_factual_details = list(dict.fromkeys(important_factual_details))[:15]

    # ── Audience takeaway ─────────────────────────────────────────────────────
    intended_audience_takeaway = _strip_visual_directions(closing)[:300].strip()

    # ── Strong original ideas (metaphors) ────────────────────────────────────
    metaphors = [m.group(0).strip() for m in _METAPHOR_RE.finditer(spoken)]
    strong_original_ideas = list(dict.fromkeys(metaphors))[:8]

    # ── Visual moments ────────────────────────────────────────────────────────
    visuals = [m.group(1).strip() for m in _VISUAL_RE.finditer(script_text)]
    important_visual_moments = list(dict.fromkeys(visuals))[:10]

    return ScriptIdentity(
        core_topic=topic or _infer_topic(spoken),
        core_thesis=core_thesis,
        emotional_promise=emotional_promise,
        central_conflict=central_conflict,
        key_story=key_story,
        key_philosophical_insight=key_philosophical_insight,
        important_factual_details=important_factual_details,
        intended_audience_takeaway=intended_audience_takeaway,
        strong_original_ideas=strong_original_ideas,
        important_visual_moments=important_visual_moments,
    )


def _infer_topic(text: str) -> str:
    """Last-resort topic guess from the script text."""
    words = text.split()[:50]
    nouns = [w for w in words if len(w) > 4 and w[0].isupper() and not w.isupper()]
    return " ".join(nouns[:3]) if nouns else ""
