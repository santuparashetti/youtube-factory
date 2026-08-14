"""Domain models for TTS pronunciation preparation.

PronunciationHint — structured pronunciation metadata for one term.
TTSPreparedScript — a canonical script + its pronunciation hints.

Neither model contains provider-specific markup. The adapter layer
converts hints to whatever format the configured TTS provider expects
(e.g. SSML <sub> for Speechify).

Canonical text is NEVER modified by any component in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PronunciationHint:
    """Pronunciation guidance for one term in the script.

    term:           The canonical spelling as it appears in the script.
    pronunciation:  Respelling guide (CAPS = stressed syllable, e.g. "DEER-gha KAA-la").
    language:       Source language (Sanskrit, Greek, Latin, …).
    source:         "dictionary" | "detected" | "manual"
    confidence:     0.0–1.0; dictionary entries are 1.0, detected are lower.
    """

    term: str
    pronunciation: str
    language: str = ""
    source: str = "dictionary"
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "pronunciation": self.pronunciation,
            "language": self.language,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class TTSPreparedScript:
    """A canonical script text paired with its pronunciation hints.

    canonical_text is NEVER modified — it remains the authoritative editorial
    artifact. The hints list describes how specific terms should be spoken.

    The adapter layer reads the hints and produces provider-specific markup
    in a separate derived text object; this model stays clean.
    """

    canonical_text: str
    hints: list[PronunciationHint] = field(default_factory=list)
    requires_review: list[PronunciationHint] = field(default_factory=list)

    @property
    def hint_count(self) -> int:
        return len(self.hints)

    @property
    def review_count(self) -> int:
        return len(self.requires_review)

    def to_dict(self) -> dict:
        return {
            "canonical_text": self.canonical_text,
            "hints": [h.to_dict() for h in self.hints],
            "requires_review": [h.to_dict() for h in self.requires_review],
        }
