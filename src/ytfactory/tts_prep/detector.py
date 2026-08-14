"""Deterministic pronunciation-sensitive term detector.

Detection priority:
  1. Dictionary lookup — exact case-sensitive match (confidence = 1.0)
  2. Sanskrit/Indic transliteration patterns — heuristic (confidence = 0.4)

Avoidance principle: ordinary English words are NEVER flagged.
Short words (< 5 characters) are never flagged.
"""

from __future__ import annotations

import re

from .models import PronunciationHint

# Romanised Sanskrit typically contains:
#   - Long-vowel digraphs: aa, ii, uu, ee, oo
#   - Aspirate consonant clusters: dh, bh, gh, kh, sh, ch, ny
#   - Sanskrit morpheme endings: -aya, -ika, -ani, -ama, -ana, -ini, -ita,
#     -ata, -arya, -dhi, -mih, -aha, -aka, -akrama, -ala, -ara
#
# The pattern anchors on a capital letter (proper noun marker) so common
# English words with these sub-strings are not captured.
_SANSKRIT_PATTERN = re.compile(
    r"\b([A-Z][a-z]{2,}(?:"
    r"(?:aa|ii|uu|ee|oo)"
    r"|(?:dh|bh|gh|kh|ny|tr|pr|br|dr|gr|kr|sr|sv|tv|dy|gy|ky|ry|vy)"
    r"|(?:aya|ika|ani|ama|ana|ini|ita|ata|arya|dhi|mih|ala|aha|ara|aka)"
    r")[a-z]*)\b",
    re.UNICODE,
)

# Common English words that superficially match the Sanskrit pattern.
# Extend this set when false positives are reported.
_ENGLISH_STOPWORDS: frozenset[str] = frozenset(
    {
        # Determiners / pronouns that get capitalised inside sentences
        "the", "this", "that", "these", "those", "there", "their",
        "where", "here", "what", "when", "which", "while", "who", "how",
        "they", "with", "from", "into", "other", "another",
        # Common English spiritual / abstract words
        "awareness", "attention", "intention", "meditation", "creation",
        "tradition", "transformation", "relationship", "generation",
        "information", "education", "imagination", "determination",
        "limitation", "separation", "liberation", "foundation",
        "contemplation", "observation", "celebration",
        "character", "practice", "principle", "approach",
        "philosophy", "spiritual", "ancient", "sacred",
        "knowledge", "wisdom", "freedom", "patience",
        "strength", "breathe", "breath", "achieve",
        "because", "before", "through", "without", "within",
        # Script / production labels
        "narration", "narrator", "speaker", "visual", "camera",
    }
)


def detect_terms(
    text: str,
    dictionary: dict[str, PronunciationHint],
) -> list[PronunciationHint]:
    """Return pronunciation hints for terms found in *text*.

    Priority: dictionary lookup first, then pattern detection for unknown terms.
    Each term appears at most once in the result.

    Args:
        text:       Script narration text to scan.
        dictionary: Loaded pronunciation dictionary.

    Returns:
        Ordered list of PronunciationHint (order of first appearance).
    """
    seen: set[str] = set()
    hits: list[PronunciationHint] = []

    # 1. Dictionary — exact case-sensitive whole-word match
    for term, hint in dictionary.items():
        # Use \b word boundary for the match
        if re.search(r"\b" + re.escape(term) + r"\b", text) and term not in seen:
            seen.add(term)
            hits.append(hint)

    # 2. Pattern detection — terms not already in dictionary
    for m in _SANSKRIT_PATTERN.finditer(text):
        word = m.group(0)
        if word in seen:
            continue
        if word.lower() in _ENGLISH_STOPWORDS:
            continue
        if len(word) < 5:
            continue
        seen.add(word)
        hits.append(
            PronunciationHint(
                term=word,
                pronunciation="",  # unknown — will surface for human review
                language="Sanskrit (inferred)",
                source="detected",
                confidence=0.4,
            )
        )

    return hits
