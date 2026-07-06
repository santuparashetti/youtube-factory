"""
SubtitleSegmenter — semantic word-boundary grouping.

Replaces fixed word-count chunking with linguistically aware subtitle breaks.

Core algorithm:
  1. Walk word boundaries left-to-right, accumulating words into a "pending cue".
  2. At each word, evaluate whether to break BEFORE it:
     - MUST break  → previous word ends with sentence terminal (. ! ?)
     - PREFER break → previous word ends with clause terminal (, ; :)
     - FORCE break  → accumulated cue would exceed MAX_CHARS_PER_LINE×MAX_LINES
                       or accumulated duration would produce CPS > MAX_CPS
  3. Apply "protected span" guards: never break WITHIN:
     - Numbers/measurements ("3.5", "42%", "100m")
     - Simple quoted spans (words inside "...")
     - Common abbreviations (Mr., Dr., etc.)
  4. Produce List[SubtitleCue] with accurate timing from word boundaries.

Two-line splitting:
  After initial segmentation, each cue text is evaluated:
  - If it fits on one line (≤ MAX_CHARS_PER_LINE) → single line
  - If it needs two lines → split at the word boundary nearest the midpoint
    that doesn't fall inside a protected span, balancing line lengths.

Design constraints:
  - Fully deterministic — same input always produces same output.
  - No LLM calls, no external dependencies.
  - O(n) in number of word boundaries.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import SubtitleCue
from .typography import SubtitleTypographer

# ── Configuration defaults (overridden by Settings) ───────────────────────────

DEFAULT_MAX_CPS = 18
DEFAULT_MAX_CHARS_PER_LINE = 42
DEFAULT_MAX_LINES = 2
DEFAULT_MIN_DURATION = 0.8  # seconds — minimum cue display time
DEFAULT_MAX_DURATION = 7.0  # seconds — very long cues are hard to read

# ── Protected span patterns ────────────────────────────────────────────────────

# Numbers with decimal or units (e.g. "3.5", "100m", "42%", "2,000")
_RE_NUMBER = re.compile(r"^\d[\d,._]*[%mkgKMGTBs]?$")

# Common abbreviations where the period is NOT a sentence boundary
_ABBREVIATIONS = frozenset(
    {
        "mr",
        "mrs",
        "ms",
        "dr",
        "prof",
        "sr",
        "jr",
        "st",
        "vs",
        "etc",
        "inc",
        "ltd",
        "corp",
        "govt",
        "dept",
        "approx",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "oct",
        "nov",
        "dec",
    }
)

# Clause-terminal punctuation: we PREFER to break after these
_CLAUSE_TERMINALS = frozenset(",;:")

# Sentence-terminal punctuation: we MUST break after these
_SENTENCE_TERMINALS = frozenset(".!?")

# Weak function words — avoid ending a cue with these (bare, no punctuation)
_NO_TRAIL = frozenset(
    {
        "a",
        "an",
        "the",
        "in",
        "on",
        "at",
        "by",
        "of",
        "to",
        "for",
        "with",
        "from",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "that",
        "this",
        "which",
        "who",
        "as",
    }
)

# Words that must not BEGIN the second display line of a two-line cue unless
# the preceding word ends with clause/sentence punctuation (natural pause).
# Never split: phrasal verbs, prepositional phrases, article-noun, aux-verb pairs.
_NO_LINE2_START = frozenset(
    {
        # Prepositions
        "for",
        "to",
        "of",
        "with",
        "on",
        "in",
        "at",
        "from",
        "by",
        # Auxiliary / linking verbs
        "is",
        "are",
        "was",
        "were",
        # Coordinating conjunctions
        "and",
        "or",
        "but",
        # Articles
        "the",
        "a",
        "an",
    }
)


@dataclass
class _PendingCue:
    """Accumulator for words being grouped into a subtitle cue."""

    words: list[dict] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w["word"] for w in self.words)

    @property
    def start(self) -> float:
        return self.words[0]["start"] if self.words else 0.0

    @property
    def end(self) -> float:
        return self.words[-1]["end"] if self.words else 0.0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def char_count(self) -> int:
        return len(self.text.replace(" ", ""))

    @property
    def cps(self) -> float:
        if self.duration <= 0:
            return 0.0
        return self.char_count / self.duration

    def is_empty(self) -> bool:
        return not self.words

    def clear(self) -> None:
        self.words.clear()


class SubtitleSegmenter:
    """
    Convert word-level timing boundaries into semantically grouped subtitle cues.

    Usage::

        segmenter = SubtitleSegmenter(max_cps=18, max_chars_per_line=42, max_lines=2)
        cues = segmenter.segment(boundaries, narration)
    """

    def __init__(
        self,
        max_cps: float = DEFAULT_MAX_CPS,
        max_chars_per_line: int = DEFAULT_MAX_CHARS_PER_LINE,
        max_lines: int = DEFAULT_MAX_LINES,
        min_duration: float = DEFAULT_MIN_DURATION,
    ) -> None:
        self._max_cps = max_cps
        self._max_chars = max_chars_per_line * max_lines
        self._max_chars_per_line = max_chars_per_line
        self._max_lines = max_lines
        self._min_duration = min_duration
        self._typo = SubtitleTypographer()

    # ── Public API ────────────────────────────────────────────────────────────

    def segment(
        self,
        boundaries: list[dict],
        narration: str = "",
    ) -> list[SubtitleCue]:
        """
        Produce semantically grouped subtitle cues from word boundaries.

        Args:
            boundaries: [{word, start, end}] from TTS provider.
            narration:  Optional raw narration text — used for fallback only.

        Returns:
            List of SubtitleCue with 1–2 display lines and accurate timing.
        """
        if not boundaries:
            return self._fallback_cues(narration)

        cues: list[SubtitleCue] = []
        pending = _PendingCue()
        in_quotes = False

        for i, boundary in enumerate(boundaries):
            word = boundary["word"]

            # ── Quote tracking ────────────────────────────────────────────────
            # Count quote marks to track open/close state.
            # Simplified: a leading " enters quote mode; trailing " exits.
            if word.startswith('"') and not in_quotes:
                in_quotes = True
            if word.endswith('"') and in_quotes:
                in_quotes = False

            # ── Decision: break BEFORE this word? ────────────────────────────
            if not pending.is_empty():
                prev_word = pending.words[-1]["word"]
                prev_bare = prev_word.rstrip(",;:.!?")
                is_abbrev = prev_bare.lower() in _ABBREVIATIONS

                sentence_end = (
                    prev_word.endswith((".", "!", "?"))
                    and not is_abbrev
                    and not _is_number_token(prev_word)
                    and not in_quotes
                )
                clause_end = prev_word.endswith((",", ";", ":")) and not in_quotes

                # Would adding this word overflow?
                trial_text = pending.text + " " + word
                trial_chars = len(trial_text.replace(" ", ""))
                trial_duration = boundary["end"] - pending.start
                trial_cps = trial_chars / max(trial_duration, 0.001)

                overflow_chars = trial_chars > self._max_chars
                overflow_cps = trial_cps > self._max_cps and len(pending.words) >= 3

                force_break = overflow_chars or overflow_cps
                prefer_break = clause_end and len(pending.words) >= 3
                must_break = sentence_end

                # Never break if we'd leave a trailing function word
                trailing_fn = word.lower().rstrip(".,;:?!") in _NO_TRAIL

                should_break = (
                    (must_break or force_break or prefer_break)
                    and not trailing_fn
                    and len(pending.words) >= 2
                )

                if should_break:
                    cues.append(self._flush(pending, len(cues) + 1))

            pending.words.append(boundary)

        # Flush any remaining words
        if not pending.is_empty():
            cues.append(self._flush(pending, len(cues) + 1))

        return cues

    def fallback_segment(
        self,
        narration: str,
        total_duration: float,
    ) -> list[SubtitleCue]:
        """
        Produce cues from raw narration when word boundaries are unavailable.
        Uses proportional timing with sentence-aware splitting.
        """
        return self._fallback_cues(narration, total_duration)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _flush(self, pending: _PendingCue, index: int) -> SubtitleCue:
        """Convert pending words into a SubtitleCue with 1 or 2 display lines."""
        text = pending.text
        start = pending.start
        end = pending.end
        pending.clear()

        lines = self._split_lines(text)
        lines = self._apply_typography(lines)
        lines = [ln for ln in lines if ln.strip()]

        return SubtitleCue(
            index=index,
            start=start,
            end=end,
            lines=lines,
        )

    def _apply_typography(self, lines: list[str]) -> list[str]:
        """
        Apply typography cleanup with continuation-aware capitalization.

        Line 1 always gets capitalize_first.  Line 2 gets capitalize_first only
        if line 1 ends with a sentence terminal (.!?) — otherwise it is a
        continuation and the first word keeps its original casing.
        """
        if len(lines) == 2:
            line1 = self._typo.clean(lines[0])
            l1_last = line1.rstrip()
            line1_ends_sentence = bool(l1_last) and l1_last[-1] in ".!?"
            line2 = (
                self._typo.clean(lines[1])
                if line1_ends_sentence
                else self._typo.clean_continuation(lines[1])
            )
            return [line1, line2]
        return self._typo.clean_lines(lines)

    def _split_lines(self, text: str) -> list[str]:
        """
        Split a cue's text into 1 or 2 linguistically balanced display lines.

        Single line if text fits within MAX_CHARS_PER_LINE.
        Two lines otherwise: find the word boundary nearest the midpoint that
        satisfies linguistic constraints (no bad-start words, no trailing
        function words without preceding punctuation).
        """
        text = text.strip()
        if len(text) <= self._max_chars_per_line:
            return [text]

        words = text.split()
        if len(words) <= 2:
            return [text]

        mid = len(text) // 2
        best_split_idx = self._find_line_split(words, mid)

        if best_split_idx <= 0 or best_split_idx >= len(words):
            return [text]

        line1 = " ".join(words[:best_split_idx])
        line2 = " ".join(words[best_split_idx:])

        if not line1.strip() or not line2.strip():
            return [text]

        if (
            len(line1) > self._max_chars_per_line
            or len(line2) > self._max_chars_per_line
        ):
            return [text]

        return [line1, line2]

    def _find_line_split(self, words: list[str], mid_chars: int) -> int:
        """
        Find the best word-split index using two-pass linguistic scoring.

        Pass 1 (strict): enforces both trailing and leading function-word rules.
        Pass 2 (permissive): only enforces the trailing rule if pass 1 finds nothing.

        A candidate at index i means split BEFORE words[i] — line 1 is words[:i],
        line 2 is words[i:].  Candidates where either resulting line would exceed
        ``max_chars_per_line`` are skipped in both passes.

        Scoring per accepted candidate:
          - Minimise distance from midpoint
          - Clause-punct bonus (-2) when word[i-1] ends with , ; :

        Returns 0 when no valid split exists.
        """
        n = len(words)
        total_len = len(" ".join(words))  # total character count of the full text

        def _best(strict: bool) -> int:
            best_idx = 0
            best_dist: float = float("inf")
            running = 0

            for i, word in enumerate(words):
                if i > 0:
                    running += 1  # one space between words
                running += len(word)

                bare = word.lower().rstrip(".,;:?!'\"")
                # Does this word carry explicit punctuation that marks a natural break?
                ends_with_punct = bool(word) and word[-1] in ".,;:!?"

                # Rule 1: never trail line 1 with a bare function word (no punctuation).
                if bare in _NO_TRAIL and not ends_with_punct:
                    continue

                # Rule 2 (strict): never start line 2 with a function word unless
                # the preceding word has clause/sentence punctuation.
                if strict and i + 1 < n:
                    next_bare = words[i + 1].lower().rstrip(".,;:?!'\"")
                    if next_bare in _NO_LINE2_START and not ends_with_punct:
                        continue

                # Both resulting lines must fit within the per-line character limit.
                line1_len = running
                line2_len = total_len - running - 1  # -1 for the inter-word space
                if (
                    line1_len > self._max_chars_per_line
                    or line2_len > self._max_chars_per_line
                ):
                    continue

                # Prefer clause boundaries (comma, semicolon, colon)
                clause_bonus = -2 if ends_with_punct and word[-1] in ",;:" else 0
                effective_dist = abs(running - mid_chars) + clause_bonus

                if 1 <= i < n - 1 and effective_dist < best_dist:
                    best_dist = effective_dist
                    best_idx = i + 1

            return best_idx

        result = _best(strict=True)
        if result == 0:
            result = _best(strict=False)
        return result

    def _fallback_cues(
        self,
        narration: str,
        total_duration: float = 0.0,
    ) -> list[SubtitleCue]:
        """
        Build subtitle cues from raw narration text when timing is unavailable.
        Uses proportional timing within the given duration.
        """
        text = narration.replace("\n", " ").strip()
        if not text:
            return []

        # Split into sentences
        sentences = _split_sentences(text)
        if not sentences or total_duration <= 0:
            if total_duration > 0:
                cue = SubtitleCue(
                    index=1,
                    start=0.0,
                    end=total_duration,
                    lines=[text[: self._max_chars]],
                )
                return [cue]
            return []

        total_chars = sum(len(s.replace(" ", "")) for s in sentences)
        cues: list[SubtitleCue] = []
        cursor = 0.0

        for idx, sentence in enumerate(sentences, start=1):
            if not sentence.strip():
                continue
            weight = len(sentence.replace(" ", "")) / max(total_chars, 1)
            duration = max(self._min_duration, weight * total_duration)
            end = min(cursor + duration, total_duration)
            lines = self._split_lines(sentence.strip())
            lines = self._apply_typography(lines)
            cues.append(SubtitleCue(index=idx, start=cursor, end=end, lines=lines))
            cursor = end

        return cues


# ── Module-level helpers ────────────────────────────────────────────────────────


def _is_number_token(word: str) -> bool:
    """Return True if word is a number or measurement (period may not be sentence-end)."""
    bare = word.rstrip(".!?,;:")
    return bool(_RE_NUMBER.match(bare))


def _split_sentences(text: str) -> list[str]:
    """
    Split text into sentences, keeping terminal punctuation attached.
    Handles common abbreviations to avoid false splits.
    """
    # Use a simple rule: split at [.!?] followed by space + uppercase
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    # Filter out very short fragments (abbreviation artifacts)
    return [p.strip() for p in parts if len(p.strip()) >= 3]
