"""
SubtitleTypographer — display-facing text normalization for subtitles.

Different from SpeechFormatter (which normalizes FOR TTS synthesis).
This normalizes FOR VISUAL DISPLAY on screen: reader-friendly punctuation,
clean unicode, no malformed patterns.

Subtitle-specific rules:
  - Ellipsis: "..." is KEPT (unlike TTS which collapses it to ".")
  - Smart quotes → straight quotes (screen rendering consistency)
  - Em dash → " - " with spaces (shorter than em dash in narrow subtitle box)
  - Malformed punct patterns repaired (",.", "?.", "!.", "..", etc.)
  - Capitalization: first letter of each cue is uppercase
  - Apostrophes: curly → straight
"""

from __future__ import annotations

import re


# Malformed punctuation patterns that must never appear in subtitles
_RE_COMMA_PERIOD = re.compile(r",\.")  # ,. → .
_RE_QUESTION_PERIOD = re.compile(r"\?\.")  # ?. → ?
_RE_EXCLAIM_PERIOD = re.compile(r"!\.")  # !. → !
_RE_SEMI_PERIOD = re.compile(r";\.+")  # ;. or ;.. → ;
_RE_COLON_PERIOD = re.compile(r":\.")  # :. → :
_RE_MULTI_PERIOD = re.compile(r"\.{4,}")  # .... → ...  (preserve 3-dot ellipsis)
_RE_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?;:])")  # " ," → ","
_RE_MULTI_SPACE = re.compile(r" {2,}")  # collapse multiple spaces

# Smart quotes and special characters
_SMART_OPEN_DOUBLE = "“"  # "
_SMART_CLOSE_DOUBLE = "”"  # "
_SMART_OPEN_SINGLE = "‘"  # '
_SMART_CLOSE_SINGLE = "’"  # '
_EM_DASH = "—"  # —
_EN_DASH = "–"  # –
_ELLIPSIS_CHAR = "…"  # …


class SubtitleTypographer:
    """
    Normalize subtitle text for visual display.

    All methods are stateless and pure — safe to share across threads.
    The main entry point is ``clean()``.
    """

    def clean(self, text: str) -> str:
        """
        Full typography normalization pipeline.

        Steps (in order):
          1. normalize_quotes   — smart quotes → straight
          2. normalize_dashes   — em/en dash → subtitle-friendly form
          3. normalize_ellipsis — Unicode ellipsis char → ...
          4. repair_punctuation — fix malformed patterns (,. ?. !. etc.)
          5. normalize_spaces   — collapse excess whitespace
          6. capitalize_first   — ensure first letter is uppercase

        Returns the cleaned string. Empty input returned unchanged.
        """
        if not text.strip():
            return text

        text = self.normalize_quotes(text)
        text = self.normalize_dashes(text)
        text = self.normalize_ellipsis(text)
        text = self.repair_punctuation(text)
        text = self.normalize_spaces(text)
        text = self.capitalize_first(text)
        return text

    def clean_lines(self, lines: list[str]) -> list[str]:
        """Clean each line independently."""
        return [self.clean(line) for line in lines]

    def normalize_quotes(self, text: str) -> str:
        """Replace curly/smart quotes with straight quotes."""
        text = text.replace(_SMART_OPEN_DOUBLE, '"')
        text = text.replace(_SMART_CLOSE_DOUBLE, '"')
        text = text.replace(_SMART_OPEN_SINGLE, "'")
        text = text.replace(_SMART_CLOSE_SINGLE, "'")
        return text

    def normalize_dashes(self, text: str) -> str:
        """
        Em dash → space-hyphen-space, en dash → "to" or hyphen.
        Subtitle boxes are narrow — em dash looks better as " - ".
        """
        text = re.sub(r"\s*" + _EM_DASH + r"\s*", " - ", text)
        text = re.sub(r"\s*" + _EN_DASH + r"\s*", " - ", text)
        return text

    def normalize_ellipsis(self, text: str) -> str:
        """Unicode ellipsis character → three ASCII periods."""
        return text.replace(_ELLIPSIS_CHAR, "...")

    def repair_punctuation(self, text: str) -> str:
        """
        Fix malformed punctuation patterns that would look wrong on screen.

        Patterns repaired:
          ,.   → .       (comma before period)
          ?.   → ?       (question mark then period)
          !.   → !       (exclamation then period)
          ;.   → ;       (semicolon then period)
          :.   → :       (colon then period)
          ....+ → ...    (four+ periods → ellipsis)
           ,   → ,       (space before comma)
        """
        text = _RE_COMMA_PERIOD.sub(".", text)
        text = _RE_QUESTION_PERIOD.sub("?", text)
        text = _RE_EXCLAIM_PERIOD.sub("!", text)
        text = _RE_SEMI_PERIOD.sub(";", text)
        text = _RE_COLON_PERIOD.sub(":", text)
        text = _RE_MULTI_PERIOD.sub("...", text)
        text = _RE_SPACE_BEFORE_PUNCT.sub(r"\1", text)
        return text

    def normalize_spaces(self, text: str) -> str:
        """Collapse multiple spaces to one and strip leading/trailing."""
        return _RE_MULTI_SPACE.sub(" ", text).strip()

    def capitalize_first(self, text: str) -> str:
        """Ensure the first non-space character is uppercase."""
        stripped = text.lstrip()
        if not stripped:
            return text
        leading = text[: len(text) - len(stripped)]
        return leading + stripped[0].upper() + stripped[1:]

    def count_repairs(self, original: str, cleaned: str) -> int:
        """Count how many characters differ (proxy for repair count)."""
        return sum(a != b for a, b in zip(original, cleaned)) + abs(
            len(original) - len(cleaned)
        )
