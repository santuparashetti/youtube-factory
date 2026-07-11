"""
SpeechFormatter — provider-independent narration text normalization.

Sits between SpeechOptimizer and any TTS provider. Receives the
optimizer's output (phrases joined with \\n\\n) and returns clean
Unicode text ready for synthesis.

Responsibilities:
  - Markdown stripping
  - Unicode normalization (smart quotes, em-dash, zero-width chars)
  - Paragraph-break → spoken-pause conversion
  - Double-period prevention  ← fixes the primary first-word clipping bug
  - Whitespace collapse

Design rules:
  - Never modifies narration meaning or intent
  - Purely textual transformation, no audio or timing logic
  - Provider-independent: all providers use the same formatter
  - Provider-specific markup (SSML, voice tags) belongs in provider adapters
"""

from __future__ import annotations

import re


class SpeechFormatter:
    """
    Normalize narration text for any TTS provider.

    Usage::

        formatter = SpeechFormatter()
        clean = formatter.format(optimizer_output, style="spiritual")

    The ``style`` hint controls only how paragraph breaks are converted to
    pauses. All other normalization steps are style-independent.
    """

    # ── Pre-compiled patterns (compiled once, reused across calls) ────────────

    # Markdown
    _RE_HEADERS = re.compile(r"^#{1,6}\s+", re.MULTILINE)
    _RE_BOLD_ITAL = re.compile(r"\*{1,3}(.+?)\*{1,3}", re.DOTALL)
    _RE_UNDERLINE = re.compile(r"\b_(.+?)_\b")
    _RE_LINKS = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
    _RE_CODE = re.compile(r"`([^`]+)`")
    _RE_HR = re.compile(r"-{3,}")
    _RE_BULLETS = re.compile(r"^\s*[-*•]\s+", re.MULTILINE)

    # Unicode / punctuation
    _RE_EM_DASH = re.compile(r"\s*—\s*")  # —
    _RE_EN_DASH = re.compile(r"\s*–\s*")  # –
    _RE_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")

    # Paragraph / pause — used in normalize_paragraphs
    # Matches a period (optionally followed by spaces) then one or more newlines.
    # Replacement: single period + space  →  avoids creating ".." when the
    # phrase already ends with a period ("word.\n\nnext" → "word. next").
    _RE_PERIOD_THEN_NEWLINES = re.compile(r"\.\s*\n+")
    _RE_REMAINING_NEWLINES = re.compile(r"\n+")

    # Defensive double-period cleanup — catches any ".." that survived above.
    # Matches two or more consecutive periods (but not more) so it doesn't
    # interact with intentional ellipsis (which is collapsed separately).
    _RE_MULTI_PERIOD = re.compile(r"\.{2,}")

    def format(self, text: str, style: str | None = None) -> str:
        """
        Normalize ``text`` for TTS synthesis.

        Steps (in order):
          1. strip_markdown
          2. normalize_unicode
          3. normalize_paragraphs  (style-dependent)
          4. normalize_punctuation (defensive cleanup after step 3)
          5. collapse_whitespace

        Args:
            text:  Raw narration text, typically the output of SpeechOptimizer.
            style: Style hint — only "spiritual" changes paragraph conversion.
                   All other values (including None) use the standard branch.

        Returns:
            Clean single-line (after whitespace collapse) Unicode string.
            Returns the input unchanged if it is empty or whitespace-only.
        """
        if not text or not text.strip():
            return text

        text = self.strip_markdown(text)
        text = self.normalize_unicode(text)
        text = self.normalize_paragraphs(text, style)
        text = self.normalize_punctuation(text)
        text = self.collapse_whitespace(text)
        return text

    # ── Individual normalization steps (public for testability) ───────────────

    def strip_markdown(self, text: str) -> str:
        """Remove markdown formatting without altering the text content."""
        text = self._RE_HEADERS.sub("", text)
        text = self._RE_BOLD_ITAL.sub(r"\1", text)
        text = self._RE_UNDERLINE.sub(r"\1", text)
        text = self._RE_LINKS.sub(r"\1", text)
        text = self._RE_CODE.sub(r"\1", text)
        text = self._RE_HR.sub(".", text)  # horizontal rule → period
        text = self._RE_BULLETS.sub("", text)
        return text

    def normalize_unicode(self, text: str) -> str:
        """Replace special Unicode characters with TTS-safe equivalents."""
        # Smart quotes
        text = text.replace("“", '"').replace("”", '"')  # " "
        text = text.replace("‘", "'").replace("’", "'")  # ' '

        # Dashes
        text = self._RE_EM_DASH.sub(", ", text)  # em dash → comma pause
        text = self._RE_EN_DASH.sub(" to ", text)  # en dash → "to"

        # Common substitutions
        text = text.replace("&", "and")
        text = text.replace(" ", " ")  # non-breaking space

        # Unicode ellipsis → three periods (normalize_punctuation then collapses to ".")
        text = text.replace("…", "...")

        # Zero-width characters (invisible, can confuse TTS tokenizers)
        text = self._RE_ZERO_WIDTH.sub("", text)

        return text

    def normalize_paragraphs(self, text: str, style: str | None) -> str:
        """
        Convert paragraph/line breaks into spoken pauses.

        Spiritual style:
          Phrases (from SpeechOptimizer) are separated by \\n\\n.
          We convert these to ". " so Edge TTS inserts a sentence-end pause.

          Critical fix — double-period prevention:
            "word.\\n\\nnext"  →  "word. next"  (strip trailing period FIRST)
            "word\\n\\nnext"   →  "word. next"  (add period normally)

          Without this fix the naive substitution \\n+ → ". " produces:
            "word.\\n\\nnext"  →  "word.. next"  (double period)
          which Edge TTS renders with an anomalous prosodic break, causing
          the first word of the following phrase to be clipped or softened.

        Standard style:
          Double newlines become a space (single-line narration).
          Single newlines also become spaces.
        """
        if style == "spiritual":
            # Step A: if a phrase already ends with ".", consuming the period
            # before the newlines prevents a double period.
            text = self._RE_PERIOD_THEN_NEWLINES.sub(". ", text)
            # Step B: remaining newlines (phrases that did NOT end with ".").
            text = self._RE_REMAINING_NEWLINES.sub(". ", text)
        else:
            text = re.sub(r"\n{2,}", " ", text)
            text = re.sub(r"\n", " ", text)

        return text

    def normalize_punctuation(self, text: str) -> str:
        """
        Clean up punctuation artefacts.

        Collapses two or more consecutive periods to a single period.
        This is a defensive step — normalize_paragraphs already prevents
        double periods, but this catches any edge cases from upstream text.

        Note: intentional "..." (ellipsis) is also collapsed to "." here,
        which is correct because Edge TTS pauses naturally at sentence ends;
        an explicit ellipsis doesn't add extra pause value.
        """
        text = self._RE_MULTI_PERIOD.sub(".", text)
        return text

    def collapse_whitespace(self, text: str) -> str:
        """Collapse all consecutive whitespace to a single space and strip ends."""
        return " ".join(text.split()).strip()
