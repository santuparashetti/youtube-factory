"""
Sentence-level emotion classifier for documentary narration.

Classifies a scene's narration into one of 12 emotional categories and
returns the matching prosody profile (rate, pitch, pause timings) that
EdgeTTSProvider applies to the synthesis call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Emotion(str, Enum):
    CURIOSITY = "curiosity"
    WONDER = "wonder"
    REFLECTION = "reflection"
    MYSTERY = "mystery"
    PEACE = "peace"
    HOPE = "hope"
    COMPASSION = "compassion"
    URGENCY = "urgency"
    SADNESS = "sadness"
    AWE = "awe"
    DETERMINATION = "determination"
    REVELATION = "revelation"


@dataclass(frozen=True)
class EmotionProfile:
    emotion: Emotion
    rate: str  # Edge TTS prosody rate, e.g. "-8%"
    pitch: str  # Edge TTS prosody pitch, e.g. "-2Hz"
    # Reserved for SSML <break/> injection — not yet wired (edge-tts strips SSML)
    pre_pause_ms: int
    post_pause_ms: int


# ── Prosody map ────────────────────────────────────────────────────────────────
# Tuned for en-US-ChristopherNeural on Microsoft Neural TTS.
# Rate: negative = slower (more gravitas), positive = faster (energy/urgency).
# Pitch: Hz offset. Positive = warmer/curious; negative = deeper/serious.
_PROFILES: dict[Emotion, EmotionProfile] = {
    Emotion.CURIOSITY: EmotionProfile(Emotion.CURIOSITY, "-3%", "+1Hz", 100, 300),
    Emotion.WONDER: EmotionProfile(Emotion.WONDER, "-8%", "+2Hz", 300, 400),
    Emotion.REFLECTION: EmotionProfile(Emotion.REFLECTION, "-10%", "-1Hz", 200, 500),
    Emotion.MYSTERY: EmotionProfile(Emotion.MYSTERY, "-12%", "-3Hz", 400, 600),
    Emotion.PEACE: EmotionProfile(Emotion.PEACE, "-8%", "-1Hz", 200, 400),
    Emotion.HOPE: EmotionProfile(Emotion.HOPE, "-5%", "+1Hz", 100, 300),
    Emotion.COMPASSION: EmotionProfile(Emotion.COMPASSION, "-6%", "+0Hz", 200, 400),
    Emotion.URGENCY: EmotionProfile(Emotion.URGENCY, "+5%", "+2Hz", 100, 200),
    Emotion.SADNESS: EmotionProfile(Emotion.SADNESS, "-12%", "-3Hz", 300, 600),
    Emotion.AWE: EmotionProfile(Emotion.AWE, "-10%", "+1Hz", 400, 500),
    Emotion.DETERMINATION: EmotionProfile(
        Emotion.DETERMINATION, "-3%", "+0Hz", 200, 300
    ),
    Emotion.REVELATION: EmotionProfile(Emotion.REVELATION, "-15%", "-2Hz", 600, 700),
}

# ── Keyword lexicons ───────────────────────────────────────────────────────────
_LEXICONS: dict[Emotion, list[str]] = {
    Emotion.CURIOSITY: [
        "what if",
        "how does",
        "why do",
        "why is",
        "could it be",
        "have you ever",
        "imagine",
        "consider",
        "wonder",
        "ask yourself",
        "question",
        "curious",
        "explore",
        "discover",
        "perhaps",
        "what would",
        "what does",
        "how many",
        "what kind",
    ],
    Emotion.WONDER: [
        "extraordinary",
        "incredible",
        "remarkable",
        "astonishing",
        "breathtaking",
        "universe",
        "vast",
        "infinite",
        "cosmic",
        "magnificent",
        "beautiful",
        "miracle",
        "transcendent",
        "profound",
        "beyond",
        "stunning",
        "incomprehensible",
        "unimaginable",
    ],
    Emotion.REFLECTION: [
        "perhaps",
        "maybe",
        "in truth",
        "beneath",
        "underneath",
        "deeper",
        "realize",
        "understand",
        "consider",
        "reflect",
        "remember",
        "look back",
        "truth is",
        "in fact",
        "we often",
        "most of us",
        "all of us",
        "think about it",
        "stop and",
    ],
    Emotion.MYSTERY: [
        "hidden",
        "secret",
        "beneath the surface",
        "unknown",
        "invisible",
        "shadow",
        "unseen",
        "lurking",
        "concealed",
        "buried",
        "unspoken",
        "silent force",
        "unseen hand",
        "mystery",
        "enigma",
        "behind",
        "operating",
        "controlling",
        "pulling",
        "without knowing",
    ],
    Emotion.PEACE: [
        "quiet",
        "still",
        "calm",
        "breathe",
        "gentle",
        "silence",
        "rest",
        "peace",
        "serene",
        "tranquil",
        "soft",
        "tender",
        "warm",
        "safe",
        "present",
        "simply",
        "enough",
        "slow down",
        "let go",
    ],
    Emotion.HOPE: [
        "yet",
        "still",
        "tomorrow",
        "possible",
        "possibility",
        "begin",
        "new",
        "light",
        "forward",
        "free",
        "choose",
        "different",
        "better",
        "change",
        "grow",
        "heal",
        "rise",
        "reclaim",
        "start",
        "step",
        "moment",
        "can",
        "will",
        "ready",
    ],
    Emotion.COMPASSION: [
        "you are not alone",
        "understand",
        "feel",
        "pain",
        "struggle",
        "heart",
        "reach out",
        "together",
        "kindness",
        "empathy",
        "grief",
        "carry",
        "burden",
        "human",
        "forgive",
        "accept",
        "love",
        "vulnerable",
        "honest",
        "real",
    ],
    Emotion.URGENCY: [
        "now",
        "must",
        "stop",
        "wake up",
        "immediately",
        "no longer",
        "time to",
        "cannot wait",
        "urgent",
        "act",
        "before it",
        "too late",
        "breaking point",
        "right now",
        "demand",
        "require",
        "every day",
        "every moment",
    ],
    Emotion.SADNESS: [
        "lost",
        "grief",
        "alone",
        "burden",
        "weight",
        "hollow",
        "empty",
        "absence",
        "gone",
        "miss",
        "mourn",
        "sorrow",
        "ache",
        "tears",
        "heartbreak",
        "loneliness",
        "faded",
        "left behind",
        "abandoned",
        "forgotten",
    ],
    Emotion.AWE: [
        "behold",
        "witness",
        "ancient",
        "thousands of years",
        "centuries",
        "look",
        "see",
        "observe",
        "watch",
        "stands",
        "endures",
        "survived",
        "timeless",
        "eternal",
        "history",
        "civilization",
        "legacy",
        "monument",
        "scale",
    ],
    Emotion.DETERMINATION: [
        "despite",
        "but still",
        "yet still",
        "keep",
        "persevere",
        "refuse",
        "stand",
        "rise",
        "fight",
        "overcome",
        "through it",
        "no matter",
        "will not",
        "regardless",
        "push",
        "resist",
        "hold on",
        "keep going",
    ],
    Emotion.REVELATION: [
        "this is",
        "the truth is",
        "here is",
        "what that means",
        "and that",
        "so here",
        "the answer",
        "simply this",
        "one thing",
        "everything changes",
        "changes everything",
        "that is why",
        "which means",
        "and so",
        "in other words",
    ],
}

_DEFAULT_EMOTION = Emotion.REFLECTION


# ── Sentence splitter ──────────────────────────────────────────────────────────


def split_sentences(text: str) -> list[str]:
    """Split narration into sentences, keeping punctuation attached."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── Scoring ────────────────────────────────────────────────────────────────────


def _score_sentence(sentence: str) -> dict[Emotion, float]:
    low = sentence.lower()
    scores: dict[Emotion, float] = {e: 0.0 for e in Emotion}

    # Structural signals
    stripped = sentence.strip()
    if stripped.endswith("?"):
        scores[Emotion.CURIOSITY] += 2.0
    if stripped.endswith("!"):
        scores[Emotion.URGENCY] += 1.5
    # Very short sentences (≤ 6 words) after the first are likely revelations
    if len(stripped.split()) <= 6:
        scores[Emotion.REVELATION] += 1.5

    # Keyword matching (multi-word phrases score higher)
    for emotion, keywords in _LEXICONS.items():
        for kw in keywords:
            if kw in low:
                scores[emotion] += 1.5 if " " in kw else 1.0

    return scores


# ── Public API ─────────────────────────────────────────────────────────────────


def classify_scene(narration: str, scene_position: float = 0.5) -> EmotionProfile:
    """
    Classify dominant emotion for a scene's narration text.

    Args:
        narration: The raw narration text for this scene.
        scene_position: 0.0 = first scene, 1.0 = last scene.
                        Applies a light arc bias (curious → reflective → hopeful).

    Returns:
        EmotionProfile with rate, pitch and pause settings for this scene.
    """
    sentences = split_sentences(narration)
    if not sentences:
        return _PROFILES[_DEFAULT_EMOTION]

    totals: dict[Emotion, float] = {e: 0.0 for e in Emotion}
    for sent in sentences:
        for emotion, score in _score_sentence(sent).items():
            totals[emotion] += score

    # Light arc bias — worth 1 point; keyword matches easily override it
    if scene_position < 0.2:
        totals[Emotion.CURIOSITY] += 1.0
    elif scene_position > 0.8:
        totals[Emotion.HOPE] += 1.0
    else:
        totals[Emotion.REFLECTION] += 0.5

    dominant = max(totals, key=lambda e: totals[e])

    if totals[dominant] == 0.0:
        if scene_position < 0.2:
            dominant = Emotion.CURIOSITY
        elif scene_position > 0.8:
            dominant = Emotion.HOPE
        else:
            dominant = _DEFAULT_EMOTION

    return _PROFILES[dominant]
