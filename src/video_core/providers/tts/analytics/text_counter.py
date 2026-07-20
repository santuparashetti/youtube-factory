"""Text counting utilities for TTS analytics."""

from __future__ import annotations

import re


def count_text(text: str) -> dict[str, int]:
    """Return character, word, and sentence counts for text."""
    characters = len(text)
    words = len(text.split())
    sentences = len(re.findall(r"[.!?]+", text)) or (1 if text.strip() else 0)
    return {
        "characters": characters,
        "words": words,
        "sentences": sentences,
    }
