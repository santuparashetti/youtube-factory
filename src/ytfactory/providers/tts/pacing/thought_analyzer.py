"""ThoughtAnalyzer — groups narration into semantic thought blocks.

Pacing philosophy for this channel
───────────────────────────────────
Silence should fall at *thought boundaries*, not grammatical sentence
boundaries.  A thought block is one or more sentences that together form a
single complete idea.  The listener needs time to absorb the idea before the
next thought begins — not after every period.

Example of correct blocking:

    "Everything you chase...             ┐
     will eventually disappear."         ┘ block 1  → 2–4 s silence

    "But there is one thing...           ┐
     that never leaves you."             ┘ block 2  → 2–3 s silence

    "It is your awareness."              → block 3 (last — no trailing silence)

Block boundary triggers
───────────────────────
A new block starts when a sentence:
  1. Opens with a contrast word  (But, Yet, However, Still, …)
  2. Opens with a shift/invitation  (Now, Remember, Consider, …)
  3. Is a short conclusive statement (≤ 5 words, starts with "It is / This is /
     You are / …", and contains at least one major concept word)
  4. Is a very short standalone (≤ 4 words, contains a major concept word, and
     the current block already has ≥ 8 words)

Silence depth scoring
──────────────────────
Every non-last block gets at least SMALL silence.  Additional score from:
  • concept density (3 points for ≥ 2 concepts, 1 for ≥ 1)
  • universal/absolute claims  (+2)
  • negation / paradox         (+2)
  • rhetorical question        (+2)
  • ellipsis present           (+1)
  • brevity bonus              (+4 for ≤ 6 words, +2 for ≤ 12)

Score ≥ 5 → INSIGHT (2.5–4 s for spiritual profile)
Score ≥ 2 → REALIZATION (1.5–2.5 s)
Score  < 2 → SMALL (0.8–1.2 s)
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from .config import THOUGHT_PROFILE_PAUSES
from .models import ThoughtBlock, ThoughtPauseCategory

# ---------------------------------------------------------------------------
# Keyword sets (same vocabulary as SentenceAnalyzer for consistency)
# ---------------------------------------------------------------------------

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
    "truth", "freedom", "free", "liberation", "enlightenment", "awakening",
    "realization", "understanding", "wisdom", "knowledge",
    # time / reality
    "moment", "present", "now", "time", "life", "death", "reality",
    "illusion", "maya", "karma", "eternity", "infinite", "eternal",
    # metaphysical
    "void", "emptiness", "nothingness", "universe", "energy", "spirit",
    "divine", "sacred", "power", "force", "nature", "light", "darkness",
    # relationships
    "love", "compassion", "acceptance", "surrender", "control",
    "connection", "belonging",
    # growth
    "purpose", "meaning", "change", "growth", "healing", "path", "journey",
    # body
    "body", "breath", "thought", "emotion", "feeling",
})

_UNIVERSALS: frozenset[str] = frozenset({
    "always", "never", "nothing", "everything", "everyone",
    "all", "every", "forever", "nowhere", "everywhere",
    "simply", "merely", "truly", "purely",
    "completely", "entirely", "absolutely",
})

_NEGATION_RE = re.compile(
    r"\b(cannot|can't|will not|won't|does not|doesn't|do not|don't|"
    r"is not|isn't|are not|aren't|was not|wasn't|never|no one|none|"
    r"nothing|nobody|nowhere)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

# Split on . ! ? followed by whitespace + an uppercase letter (new sentence).
# Requiring an uppercase start means "Everything you chase... will" is NOT split
# (lowercase "w") while "Peace is within. But desire" IS split (uppercase "B").
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _split_sentences(text: str) -> list[str]:
    """Split narration into sentences, preserving ellipsis as an internal pause."""
    normalized = re.sub(r"\s*\n+\s*", " ", text.strip())
    parts = _SENTENCE_SPLIT_RE.split(normalized)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Block-boundary triggers
# ---------------------------------------------------------------------------

_CONTRAST_OPENERS: frozenset[str] = frozenset({
    "but", "yet", "however", "still", "although", "though",
    "nevertheless", "nonetheless",
})

_CONTRAST_PHRASES = ("and yet", "even so", "but then", "and so")

_SHIFT_OPENERS: frozenset[str] = frozenset({
    "now", "remember", "consider", "notice", "understand",
    "realize", "look", "ask", "think", "feel", "know",
    "instead", "therefore", "thus",
})

# Short definitive starters that signal a standalone concluding thought.
_CONCLUSIVE_STARTERS = (
    "it is", "this is", "that is", "you are", "we are",
    "there is", "there are", "life is", "truth is",
    "what remains", "what stays", "all that",
)


def _tokens(sentence: str) -> set[str]:
    return {w.lower().strip(".,!?;:\"'()[]") for w in sentence.split()}


def _new_block_trigger(sentence: str, current_block: list[str]) -> str | None:
    """Return a trigger label if *sentence* should start a new thought block.

    Returns None to continue the current block.
    """
    s = sentence.strip()
    if not s:
        return None

    words = s.split()
    first = words[0].lower().strip(".,!?;:\"'")
    s_low = s.lower()

    # 1 — Contrast opener (always signals a new thought direction)
    if first in _CONTRAST_OPENERS:
        return "contrast"
    for phrase in _CONTRAST_PHRASES:
        if s_low.startswith(phrase):
            return "contrast"

    # 2 — Shift / invitation opener (when the current block already has content)
    if first in _SHIFT_OPENERS and current_block:
        return "shift"

    # 3 — Short conclusive statement (≤ 5 words, starts with a definitive phrase,
    #     and contains at least one major concept word)
    if len(words) <= 5:
        toks = _tokens(s)
        has_concept = bool(toks & _MAJOR_CONCEPTS)
        if has_concept:
            for starter in _CONCLUSIVE_STARTERS:
                if s_low.startswith(starter):
                    return "conclusive"

    # 4 — Very short standalone (≤ 4 words, contains a concept word,
    #     current block is substantial enough to stand alone)
    if (
        len(words) <= 4
        and len(" ".join(current_block).split()) >= 8
        and bool(_tokens(s) & _MAJOR_CONCEPTS)
    ):
        return "short_standalone"

    return None


# ---------------------------------------------------------------------------
# Block scoring
# ---------------------------------------------------------------------------

def _score_block(sentences: list[str]) -> tuple[ThoughtPauseCategory, list[str]]:
    """Score a thought block for how much contemplative silence it deserves."""
    text = " ".join(sentences)
    words = text.split()
    word_count = len(words)
    toks = _tokens(text)
    triggers: list[str] = []
    score = 0

    # Brevity bonus — shorter blocks punch harder
    if word_count <= 6:
        score += 4
        triggers.append(f"very_short({word_count}w)")
    elif word_count <= 12:
        score += 2
        triggers.append(f"short({word_count}w)")

    # Concept density
    concept_hits = toks & _MAJOR_CONCEPTS
    if len(concept_hits) >= 2:
        score += 3
        triggers.append(f"multi_concept({', '.join(sorted(concept_hits)[:2])})")
    elif concept_hits:
        score += 1
        triggers.append(f"concept({next(iter(concept_hits))})")

    # Universal / absolute claims
    if toks & _UNIVERSALS:
        score += 2
        triggers.append("universal")

    # Negation / paradox
    if _NEGATION_RE.search(text):
        score += 2
        triggers.append("negation")

    # Rhetorical question
    if any(s.strip().endswith("?") for s in sentences) and word_count <= 15:
        score += 2
        triggers.append("rhetorical_question")

    # Ellipsis — internal dramatic pause marker (the narration author intended weight)
    if "..." in text:
        score += 1
        triggers.append("ellipsis")

    if score >= 5:
        return ThoughtPauseCategory.INSIGHT, triggers
    elif score >= 2:
        return ThoughtPauseCategory.REALIZATION, triggers
    else:
        return ThoughtPauseCategory.SMALL, triggers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ThoughtAnalyzer:
    """Splits narration into semantic thought blocks with contemplative silence.

    Unlike the sentence-level ``SentenceAnalyzer``, this class groups sentences
    into logical idea units and assigns silence at *thought boundaries* only —
    giving the listener time to absorb each complete idea.

    Usage::

        analyzer = ThoughtAnalyzer()
        blocks = analyzer.analyze(narration, profile="spiritual")
        for b in blocks:
            print(b.text, "→", b.pause_ms, "ms", b.pause_category.value)
    """

    def analyze(
        self,
        narration: str,
        profile: str = "spiritual",
        rng: random.Random | None = None,
    ) -> list[ThoughtBlock]:
        """Return thought blocks with silence durations for *narration*.

        The last block always has ``pause_category=NONE`` and ``pause_ms=0``.
        All other blocks receive a silence duration sampled from the profile's
        range for their depth category.
        """
        sentences = _split_sentences(narration)
        if not sentences:
            return []

        groups = self._group(sentences)
        ranges = THOUGHT_PROFILE_PAUSES.get(profile, THOUGHT_PROFILE_PAUSES["spiritual"])
        rng = rng or random

        blocks: list[ThoughtBlock] = []
        for i, group in enumerate(groups):
            is_last = i == len(groups) - 1
            text = " ".join(group)
            category, triggers = _score_block(group)

            if is_last:
                pause_ms = 0
                category = ThoughtPauseCategory.NONE
            else:
                pause_range = getattr(ranges, category.value)
                pause_ms = rng.randint(pause_range.min_ms, pause_range.max_ms)

            blocks.append(ThoughtBlock(
                sentences=group,
                text=text,
                pause_ms=pause_ms,
                pause_category=category,
                triggers=triggers,
            ))

        return blocks

    # ── Internal ──────────────────────────────────────────────────────────────

    def _group(self, sentences: list[str]) -> list[list[str]]:
        """Group sentences into thought blocks using boundary trigger rules."""
        if not sentences:
            return []

        groups: list[list[str]] = [[sentences[0]]]
        for sent in sentences[1:]:
            if _new_block_trigger(sent, groups[-1]):
                groups.append([sent])
            else:
                groups[-1].append(sent)

        return groups
