"""SentenceAnalyzer — scores narration sentences for contemplative pause weight.

Scoring is rule-based (no LLM calls) and operates in two passes:

  Pass 1: Score each sentence independently (concept density, length, rhetorical structure).
  Pass 2: If sentence[i+1] opens with a major concept keyword, add a pre-concept
          pause supplement to sentence[i]'s pause_ms.

Score → PauseCategory mapping (before profile scaling):
  0–2  → SHORT   (connecting/transitional sentence)
  3–4  → MEDIUM  (important statement)
  5+   → LONG    (major realization / profound insight)

The last sentence always receives PauseCategory.NONE (no trailing silence).
"""

from __future__ import annotations

import random
import re

from .config import PROFILE_PAUSES, PauseRange
from .models import PauseCategory, SentenceAnalysis

# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

# Core concepts that carry philosophical / spiritual weight.
# A sentence containing these words is more likely to need contemplative space.
_MAJOR_CONCEPTS: frozenset[str] = frozenset({
    # inner states
    "peace", "joy", "happiness", "bliss", "contentment", "serenity",
    "stillness", "silence", "calm", "clarity",
    # suffering / desire
    "suffering", "desire", "attachment", "craving", "longing", "fear",
    "anger", "pain", "grief", "sorrow",
    # identity / consciousness
    "self", "ego", "mind", "soul", "consciousness", "awareness",
    "identity", "being", "existence",
    # liberation / truth
    "truth", "freedom", "liberation", "enlightenment", "awakening",
    "realization", "understanding", "wisdom", "knowledge",
    # time / reality
    "moment", "present", "now", "time", "life", "death", "reality",
    "illusion", "maya", "karma", "eternity", "infinite", "eternal",
    # metaphysical
    "void", "emptiness", "nothingness", "universe", "energy", "spirit",
    "divine", "sacred", "power", "force", "nature",
    # relationships
    "love", "compassion", "acceptance", "surrender", "control",
    "connection", "belonging",
    # growth
    "purpose", "meaning", "change", "growth", "healing", "path", "journey",
    # body
    "body", "breath", "thought", "emotion", "feeling",
})

# Universal/absolute quantifiers that elevate a statement to a general truth.
_UNIVERSALS: frozenset[str] = frozenset({
    "always", "never", "nothing", "everything", "everyone",
    "all", "every", "forever", "nowhere", "everywhere",
    "only", "simply", "merely", "truly", "purely",
    "completely", "entirely", "absolutely",
})

# Negation patterns common in philosophical speech ("cannot find", "is not real").
_NEGATION_RE = re.compile(
    r"\b(cannot|can't|will not|won't|does not|doesn't|do not|don't|"
    r"is not|isn't|are not|aren't|was not|wasn't|never|no )\b",
    re.IGNORECASE,
)

# Sentence boundary splitter: split after . ! ? followed by whitespace.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Rhetorical question — questions typically need LESS pause to keep energy.
_QUESTION_RE = re.compile(r"\?\s*$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_sentences(text: str) -> list[str]:
    """Split narration into individual sentences, normalising line breaks first."""
    normalized = re.sub(r"\s*\n+\s*", " ", text.strip())
    parts = _SENTENCE_SPLIT_RE.split(normalized)
    return [p.strip() for p in parts if p.strip()]


def _token_set(sentence: str) -> set[str]:
    """Lower-case word tokens stripped of surrounding punctuation."""
    return {w.lower().strip(".,!?;:\"'()[]") for w in sentence.split()}


def _score_sentence(sentence: str) -> tuple[int, list[str]]:
    """Return (raw_score, triggers) for a single sentence.

    Higher score → longer contemplative pause.
    """
    words = sentence.split()
    word_count = len(words)
    tokens = _token_set(sentence)
    score = 0
    triggers: list[str] = []

    # ── Concept keyword density ──────────────────────────────────────────────
    matches = _MAJOR_CONCEPTS & tokens
    if len(matches) >= 2:
        score += 3
        triggers.append(f"multi-concept({', '.join(sorted(matches)[:3])})")
    elif len(matches) == 1:
        score += 1
        triggers.append(f"concept({next(iter(matches))})")

    # ── Concept opener (sentence starts with a key concept) ─────────────────
    first = words[0].lower().strip(".,!?;:\"'()") if words else ""
    if first in _MAJOR_CONCEPTS:
        score += 2
        triggers.append(f"concept-opener({first})")

    # ── Sentence brevity (pithy = impactful) ────────────────────────────────
    if word_count <= 5:
        score += 3
        triggers.append(f"very-short({word_count}w)")
    elif word_count <= 8:
        score += 2
        triggers.append(f"short({word_count}w)")

    # ── Universal / absolute statements ─────────────────────────────────────
    universals = _UNIVERSALS & tokens
    if universals:
        score += 1
        triggers.append(f"universal({next(iter(universals))})")

    # ── Negation patterns (philosophical negations carry weight) ─────────────
    if _NEGATION_RE.search(sentence):
        score += 1
        triggers.append("negation")

    # ── Rhetorical question (reduce score — questions propel forward) ─────────
    if _QUESTION_RE.search(sentence):
        score -= 1
        triggers.append("question(-1)")

    return score, triggers


def _sample(pause_range: PauseRange, rng: random.Random | None = None) -> int:
    """Sample a pause uniformly from the range. Uses module-level RNG by default."""
    r = rng or random
    return r.randint(pause_range.min_ms, pause_range.max_ms)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SentenceAnalyzer:
    """Analyzes narration sentences and assigns contemplative pause durations.

    Usage::

        analyzer = SentenceAnalyzer()
        sentences = analyzer.analyze(narration, profile="spiritual")
        for s in sentences:
            print(s.text, s.pause_ms, "ms", s.triggers)
    """

    def analyze(
        self,
        narration: str,
        profile: str = "spiritual",
        rng: random.Random | None = None,
    ) -> list[SentenceAnalysis]:
        """Return one SentenceAnalysis per sentence.

        The last sentence always has pause_category=NONE and pause_ms=0.
        All other sentences get a pause sampled from the profile's appropriate range.
        A pre-concept supplement is added to sentence[i] when sentence[i+1] opens
        with a major concept word.
        """
        pauses = PROFILE_PAUSES.get(profile, PROFILE_PAUSES["spiritual"])
        raw = _split_sentences(narration)

        if not raw:
            return []

        results: list[SentenceAnalysis] = []

        for i, sentence in enumerate(raw):
            is_last = i == len(raw) - 1
            score, triggers = _score_sentence(sentence)

            if is_last:
                category = PauseCategory.NONE
                pause_ms = 0
            elif score <= 2:
                category = PauseCategory.SHORT
                pause_ms = _sample(pauses.short, rng)
            elif score <= 4:
                category = PauseCategory.MEDIUM
                pause_ms = _sample(pauses.medium, rng)
            else:
                category = PauseCategory.LONG
                pause_ms = _sample(pauses.long, rng)

            results.append(SentenceAnalysis(
                text=sentence,
                score=score,
                pause_category=category,
                pause_ms=pause_ms,
                triggers=triggers,
            ))

        # Pass 2 — pre-concept supplement
        # If the NEXT sentence opens with a major concept, add extra breathing room
        # to the CURRENT sentence's post-pause so the concept lands with full weight.
        for i in range(len(results) - 1):
            next_words = results[i + 1].text.split()
            if not next_words:
                continue
            next_first = next_words[0].lower().strip(".,!?;:\"'()")
            if next_first in _MAJOR_CONCEPTS and results[i].pause_category != PauseCategory.NONE:
                extra = _sample(pauses.concept_pre, rng)
                results[i].pause_ms += extra
                results[i].triggers.append(f"pre-concept({next_first},+{extra}ms)")

        return results
