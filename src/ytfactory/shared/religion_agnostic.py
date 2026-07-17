"""Religion-agnostic presentation checker (ADR-0012).

Scans narration text and publish metadata for terms that violate the
religion-agnostic presentation policy: tradition names, named scripture
texts, and Sanskrit labels.

Returns warnings — never hard errors.  Human review is required for
edge cases (e.g. a teacher's name that implies a lineage title).
"""

from __future__ import annotations

import re

# (pattern, human-readable label) pairs.
# Patterns are case-insensitive and word-boundary anchored where practical.
_FLAGGED: list[tuple[str, str]] = [
    # Tradition / religion names
    (r"\bvedanta\b", "tradition name: Vedanta"),
    (r"\badvaita\b", "tradition name: Advaita"),
    (r"\bhinduism\b", "religion label: Hinduism"),
    (r"\bhindu\b", "religion label: Hindu"),
    (r"\bsanatan\b", "tradition name: Sanatan Dharma"),
    # Named texts
    (r"\bbhagavad\b", "named text: Bhagavad Gita"),
    (r"\bgita\b", "named text: Gita"),
    (r"\bupanishad", "named text: Upanishad(s)"),
    (r"\bpurana", "named text: Purana(s)"),
    # Sanskrit label markers (the word "Sanskrit" itself appearing in narration)
    (r"\bsanskrit\b", "Sanskrit label — translate meaning instead"),
]

_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(pat, re.IGNORECASE), label) for pat, label in _FLAGGED
]

_CONTEXT_CHARS = 40


def check(text: str) -> list[str]:
    """Return warning strings for each flagged-term occurrence found in *text*.

    Returns an empty list when the text is clean.
    Each warning includes a short excerpt for context so the reviewer can
    decide quickly whether it's a genuine violation or an edge case.
    """
    warnings: list[str] = []
    for pattern, label in _COMPILED:
        for m in pattern.finditer(text):
            start = max(0, m.start() - _CONTEXT_CHARS)
            end = min(len(text), m.end() + _CONTEXT_CHARS)
            excerpt = text[start:end].replace("\n", " ").strip()
            warnings.append(
                f"[ADR-0012] {label} — context: '...{excerpt}...'"
            )
    return warnings
