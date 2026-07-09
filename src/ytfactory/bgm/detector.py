"""CategoryDetector — maps video topic to the most suitable BGM category."""

from __future__ import annotations

from .config import DEFAULT_CATEGORY


_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "spiritual": [
        "spiritual",
        "soul",
        "meditation",
        "mindfulness",
        "awakening",
        "consciousness",
        "divine",
        "sacred",
        "enlightenment",
        "karma",
        "dharma",
        "peace",
        "silence",
        "within",
        "inner",
        "self",
        "wisdom",
        "ego",
        "liberation",
        "surrender",
        "bliss",
        "faith",
        "prayer",
        "force",
        "energy",
        "universe",
        "truth",
        "lie",
        "lied",
        "happiness",
        "reality",
        "illusion",
        "perception",
        "maya",
        "atman",
        "brahman",
        "tao",
        "zen",
        "sufi",
        "mystic",
        "transcend",
    ],
    "meditation": [
        "meditation",
        "breathe",
        "calm",
        "relax",
        "stress",
        "anxiety",
        "mindful",
        "tranquil",
        "breath",
        "focus",
        "sleep",
        "relief",
        "tension",
        "reset",
        "ground",
        "centered",
        "presence",
    ],
    "cinematic_ambient": [
        "cinematic",
        "journey",
        "discover",
        "world",
        "universe",
        "cosmos",
        "space",
        "science",
        "nature",
        "earth",
        "exploration",
        "adventure",
        "wonder",
        "awe",
        "vast",
        "planet",
        "galaxy",
        "star",
    ],
    "emotional_documentary": [
        "emotion",
        "documentary",
        "history",
        "story",
        "struggle",
        "overcome",
        "true",
        "real",
        "human",
        "social",
        "war",
        "conflict",
        "survival",
        "revolution",
        "legacy",
        "empire",
        "untold",
        "forgotten",
        "hidden",
    ],
    "inspirational": [
        "inspire",
        "motivat",
        "success",
        "achieve",
        "dream",
        "goal",
        "change",
        "transform",
        "better",
        "grow",
        "power",
        "rise",
        "courage",
        "persist",
        "discipline",
        "habit",
        "mindset",
        "unlock",
        "secret",
    ],
    "calm_piano": [
        "piano",
        "classical",
        "gentle",
        "soft",
        "tender",
        "love",
        "heart",
        "feel",
        "beautiful",
        "memory",
        "nostalgia",
        "grief",
        "loss",
        "longing",
        "farewell",
    ],
    "nature_ambient": [
        "nature",
        "forest",
        "ocean",
        "rain",
        "wind",
        "mountain",
        "river",
        "bird",
        "animal",
        "earth",
        "season",
        "garden",
        "wilderness",
        "wildlife",
        "ecology",
    ],
}


def detect_category(
    title: str,
    scene_titles: list[str] | None = None,
    narration_excerpt: str | None = None,
) -> str:
    """Return the best matching BGM category for the given video topic.

    Weights: title keywords count double; scene titles once; narration once.
    Falls back to *DEFAULT_CATEGORY* when no keyword matches.
    """
    title_text = title.lower()
    scene_text = " ".join(scene_titles or []).lower()
    narration_text = (narration_excerpt or "").lower()

    scores: dict[str, int] = {cat: 0 for cat in _CATEGORY_KEYWORDS}

    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in title_text:
                scores[category] += 2  # title carries more weight
            if kw in scene_text:
                scores[category] += 1
            if kw in narration_text:
                scores[category] += 1

    best_cat = max(scores, key=lambda c: scores[c])
    return best_cat if scores[best_cat] > 0 else DEFAULT_CATEGORY
