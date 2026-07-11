"""
Speech Optimizer — converts written narration into spoken narration.

Sits between Scene Planner and TTS. Receives the raw narration string from
scene-plan.json and returns optimized text with punctuation-based pauses.

Output format: phrases separated by \\n\\n.
  edge-tts _prepare_text() converts \\n+ → ". " (sentence-end pause),
  so each \\n\\n separator becomes an audible silence without any SSML.

Never produces SSML. Always returns clean Unicode text.
"""

from __future__ import annotations

import re

from .emotion import Emotion, classify_scene, split_sentences


# Important vocabulary: philosophical, spiritual, emotional, and documentary terms.
# Single-word phrases matching these are capitalised so Edge TTS gives extra stress.
_EMPHASIS_VOCAB: frozenset[str] = frozenset(
    {
        # philosophical / spiritual
        "desire",
        "truth",
        "love",
        "death",
        "life",
        "soul",
        "god",
        "faith",
        "hope",
        "fear",
        "freedom",
        "power",
        "choice",
        "change",
        "purpose",
        "meaning",
        "karma",
        "dharma",
        "peace",
        "war",
        "justice",
        "wisdom",
        "mind",
        "ego",
        "self",
        "time",
        "silence",
        "courage",
        "pain",
        "joy",
        "sacrifice",
        "devotion",
        "consciousness",
        "awareness",
        "liberation",
        "surrender",
        "compassion",
        "forgiveness",
        "anger",
        "grief",
        "rage",
        "bliss",
        "suffering",
        "enlightenment",
        "duty",
        "honor",
        "pride",
        "shame",
        "guilt",
        "rebellion",
        "resistance",
        "submission",
        "empire",
        # documentary / narrative
        "discovery",
        "revolution",
        "crisis",
        "victory",
        "defeat",
        "legacy",
        "secret",
        "mystery",
        "transformation",
        "betrayal",
        "rise",
        "fall",
        "collapse",
        "birth",
        "end",
        "beginning",
        "glory",
        "ruin",
        "hunger",
        "thirst",
        "search",
        "quest",
        "journey",
        "return",
        "exile",
    }
)


# Split BEFORE subordinating conjunctions (they open a new dependent clause).
_SUBORD_RE = re.compile(
    r"\s+(?=\b(?:because|although|though|while|when|where|unless|since|whereas)\b)",
    re.IGNORECASE,
)

# Split at comma + coordinating conjunction (e.g. "force, and we don't").
# Requiring a comma avoids splitting "bread and butter" type phrases.
_COORD_RE = re.compile(
    r",\s+(?=\b(?:and|but|or|so|yet)\b)",
    re.IGNORECASE,
)

# Question/curiosity openers that benefit from a beat after the opening phrase.
_QUESTION_OPENERS = (
    "what if",
    "have you ever",
    "imagine",
    "could it be",
    "what would",
    "what does",
    "how does",
    "why do",
    "why is",
    "consider",
    "think about",
    "ask yourself",
)

# Function words that look awkward as the last word of a phrase.
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
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
    }
)


class SpeechOptimizer:
    """
    Transforms written narration into speech-ready text.

    Responsibilities:
    - Split long sentences into short spoken phrases (≤ 8–13 words by emotion).
    - Insert natural pauses via punctuation (commas, periods, paragraph breaks).
    - Apply curiosity/wonder emphasis: ellipsis beat after question openers.
    - Preserve meaning, timestamps, and scene mapping completely.

    Provider-independent: output is always clean text. The `supports_ssml`
    flag is reserved for future providers (Azure, OpenAI TTS) that can use
    SSML for richer control — the optimizer interface stays stable.
    """

    def optimize(
        self,
        text: str,
        style: str | None = None,
        scene_position: float = 0.5,
        supports_ssml: bool = False,
        keywords: list[str] | None = None,
    ) -> str:
        """
        Convert written narration into spoken narration.

        Args:
            text: Raw narration from scene-plan.json.
            style: Style hint ("spiritual", "documentary", …). Reserved.
            scene_position: 0.0 = first scene, 1.0 = last scene.
                            Used by the emotion classifier for arc bias.
            supports_ssml: Reserved for future SSML-capable providers.
            keywords: Optional scene title or topic words used to boost
                      emphasis on key concepts (capitalises matching
                      single-word phrases for Edge TTS stress cues).

        Returns:
            Optimized text with \\n\\n phrase breaks. Empty input is returned
            unchanged.
        """
        if not text or not text.strip():
            return text

        profile = classify_scene(text, scene_position)
        emotion = profile.emotion
        limit = _phrase_limit(emotion)

        sentences = split_sentences(text)
        if not sentences:
            return text

        phrases: list[str] = []
        for sent in sentences:
            phrases.extend(_process_sentence(sent, limit, emotion))

        topic_words = _extract_topic_words(keywords)
        phrases = _apply_keyword_emphasis(phrases, topic_words)

        return "\n\n".join(p for p in phrases if p.strip())


# ── Internal helpers (module-level functions keep the class thin) ─────────────


def _phrase_limit(emotion: Emotion) -> int:
    """Maximum words per spoken phrase. Shorter = more dramatic pauses."""
    _LIMITS: dict[Emotion, int] = {
        Emotion.URGENCY: 7,
        Emotion.REVELATION: 8,
        Emotion.MYSTERY: 9,
        Emotion.SADNESS: 9,
        Emotion.REFLECTION: 9,
        Emotion.DETERMINATION: 10,
        Emotion.CURIOSITY: 10,
        Emotion.WONDER: 10,
        Emotion.COMPASSION: 11,
        Emotion.AWE: 11,
        Emotion.HOPE: 13,
        Emotion.PEACE: 13,
    }
    return _LIMITS.get(emotion, 10)


def _process_sentence(sentence: str, limit: int, emotion: Emotion) -> list[str]:
    """
    Split one sentence into speakable phrases of at most `limit` words.

    Strategy (in priority order):
    1. If already short enough → apply opener emphasis and return.
    2. Split at comma + coordinating conjunction ("…force, and we…").
    3. Split at subordinating conjunction ("…because it…").
    4. Mechanical word-count split (guaranteed to terminate).

    Each step recurses so that parts produced by step 2/3 go through the
    same splitting if they are still too long.
    """
    words = sentence.split()

    # ── Base case ─────────────────────────────────────────────────────────
    if len(words) <= limit:
        return [_apply_opener(sentence, emotion)]

    # ── Pass 1: comma + coordinator ───────────────────────────────────────
    parts = _COORD_RE.split(sentence)
    if len(parts) == 1:
        # ── Pass 2: subordinating conjunction ─────────────────────────────
        parts = _SUBORD_RE.split(sentence)

    if len(parts) > 1:
        # Keep only non-trivial parts (≥ 3 words)
        valid = [p.strip() for p in parts if len(p.split()) >= 3]
        if len(valid) > 1:
            result: list[str] = []
            for i, part in enumerate(valid):
                # Non-final parts must end with punctuation for natural flow
                if i < len(valid) - 1 and part and part[-1] not in ".!?,;:":
                    part += ","
                # Recurse — opener ellipsis is applied inside the base case
                result.extend(_process_sentence(part, limit, emotion))
            return result

    # ── Pass 3: mechanical fallback ───────────────────────────────────────
    return _mechanical_split(sentence, limit, emotion)


def _mechanical_split(text: str, limit: int, emotion: Emotion) -> list[str]:
    """
    Hard split at word-count boundary with three quality guards:
    - Don't end a phrase on a dangling function word (preposition, article).
    - Absorb trailing fragments shorter than 3 words into the current chunk
      rather than leaving them orphaned (e.g. avoids "and fall." alone).
    - Append a comma to non-final phrases that lack terminal punctuation.
    """
    words = text.split()
    chunks: list[str] = []
    i = 0

    while i < len(words):
        end = min(i + limit, len(words))

        # If the remainder after this chunk would be a very short fragment,
        # absorb it now rather than leaving it orphaned on the next pass.
        remaining = len(words) - end
        if 0 < remaining < 3:
            end = len(words)

        # Walk back from the boundary to avoid orphaned function words.
        while end > i + 3 and words[end - 1].lower().rstrip(".,;") in _NO_TRAIL:
            end -= 1

        chunk = " ".join(words[i:end])

        # Add comma to non-final phrases that lack terminal punctuation.
        if end < len(words) and chunk and chunk[-1] not in ".!?,;:":
            chunk += ","

        chunks.append(_apply_opener(chunk, emotion))
        i = end

    return chunks


def _extract_topic_words(keywords: list[str] | None) -> frozenset[str]:
    """Extract lowercase, punctuation-stripped words from scene title keywords."""
    if not keywords:
        return frozenset()
    words: set[str] = set()
    for kw in keywords:
        for word in kw.split():
            clean = word.lower().strip(".,!?;:'\"()")
            if len(clean) >= 4:
                words.add(clean)
    return frozenset(words)


def _apply_keyword_emphasis(
    phrases: list[str], topic_words: frozenset[str]
) -> list[str]:
    """
    Capitalise single-word key phrases so Edge TTS gives them extra stress.

    Only acts on phrases that are a single meaningful word (ignoring trailing
    punctuation) and that match either the curated _EMPHASIS_VOCAB or the
    scene-specific topic_words.  Multi-word phrases are left unchanged — their
    natural isolation via \\n\\n already creates audible pauses around them.
    """
    result: list[str] = []
    for phrase in phrases:
        core = phrase.strip()
        # Strip trailing punctuation to test the bare word
        bare = core.rstrip(".,!?;:").strip()
        words = bare.split()
        if len(words) == 1:
            word_lower = words[0].lower()
            if word_lower in _EMPHASIS_VOCAB or word_lower in topic_words:
                # Preserve trailing punctuation; capitalise the word itself
                suffix = core[len(bare) :]
                result.append(bare.upper() + suffix)
                continue
        result.append(phrase)
    return result


def _apply_opener(phrase: str, emotion: Emotion) -> str:
    """
    Add a rhetorical beat after question openers in CURIOSITY/WONDER scenes.

    Example:
        "What if the life you're living isn't actually yours?"
        → "What if...\n\nthe life you're living isn't actually yours?"

    The "...\n\n" becomes ". " in edge-tts _prepare_text(), creating an
    audible pause between "What if." and the main thought.

    Only applied when:
    - Emotion is CURIOSITY or WONDER.
    - Phrase starts with a recognised question opener.
    - There are at least 3 meaningful words after the opener.
    """
    if emotion not in (Emotion.CURIOSITY, Emotion.WONDER):
        return phrase

    low = phrase.lower()
    for opener in _QUESTION_OPENERS:
        if low.startswith(opener):
            tail = phrase[len(opener) :].lstrip()
            # Only split if the rest of the phrase is substantial
            if len(tail.split()) >= 3:
                head = phrase[: len(opener)]
                return head + "...\n\n" + tail
            break

    return phrase
