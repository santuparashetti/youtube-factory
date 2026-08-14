"""TTSPreparationService — main entry point for TTS pronunciation preparation.

Accepts the canonical scene narration text (after human review, after scene
splitting). Returns a TTSPreparedScript containing the canonical text plus
structured pronunciation hints.

The canonical text is NEVER modified. This service is:
  - Stateless (new instance per call or reusable — both safe)
  - Deterministic (no LLM calls, no randomness)
  - Non-blocking (missing dictionary → empty hints, pipeline continues)
"""

from __future__ import annotations

from loguru import logger

from .detector import detect_terms
from .dictionary import get_dictionary
from .models import PronunciationHint, TTSPreparedScript

# Confidence below this threshold → surface for human review instead of
# applying automatically. Dictionary entries (confidence=1.0) always apply.
_REVIEW_THRESHOLD = 0.6


class TTSPreparationService:
    """Prepare pronunciation hints for a single narration segment.

    Usage:
        service = TTSPreparationService()
        prepared = service.prepare("Dirghakala means practice over time.")
        # prepared.canonical_text is unchanged
        # prepared.hints contains PronunciationHint(term="Dirghakala", ...)
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._dictionary = get_dictionary(config_path)

    def prepare(self, canonical_text: str) -> TTSPreparedScript:
        """Detect pronunciation-sensitive terms and return structured hints.

        The canonical_text is preserved exactly. Only the hints list
        describes how to speak certain terms differently.

        Args:
            canonical_text: Accepted narration text for one TTS segment.
                            This text must NOT be mutated anywhere in this
                            method or in any adapter that consumes the result.

        Returns:
            TTSPreparedScript with the original text + pronunciation hints.
        """
        if not canonical_text or not canonical_text.strip():
            return TTSPreparedScript(canonical_text=canonical_text)

        all_hints = detect_terms(canonical_text, self._dictionary)

        trusted: list[PronunciationHint] = []
        needs_review: list[PronunciationHint] = []

        for hint in all_hints:
            if hint.confidence >= _REVIEW_THRESHOLD and hint.pronunciation:
                trusted.append(hint)
            else:
                needs_review.append(hint)

        total = len(trusted) + len(needs_review)
        if total > 0:
            logger.info(
                "TTS PREP: detected {} pronunciation-sensitive term(s) — "
                "{} trusted, {} require review",
                total,
                len(trusted),
                len(needs_review),
            )
        if trusted:
            logger.info(
                "TTS PREP: applied {} trusted mapping(s): {}",
                len(trusted),
                ", ".join(h.term for h in trusted),
            )
        if needs_review:
            logger.warning(
                "TTS PREP: {} term(s) need pronunciation review: {}",
                len(needs_review),
                ", ".join(h.term for h in needs_review),
            )

        return TTSPreparedScript(
            canonical_text=canonical_text,
            hints=trusted,
            requires_review=needs_review,
        )
