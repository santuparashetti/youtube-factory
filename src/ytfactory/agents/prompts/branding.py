"""
Atma Theory channel branding — variation libraries for welcome and closing.

Called once per script generation to select fresh variants.
No state is persisted — rotation happens naturally through random selection.
"""

from __future__ import annotations

import random

WELCOME_VARIATIONS: list[str] = [
    "Welcome to Atma Theory... where ancient wisdom meets modern life.",
    "Welcome to Atma Theory... ancient answers to modern questions.",
    "Welcome to Atma Theory... where timeless wisdom helps us navigate today's world.",
    "Welcome to Atma Theory... together we explore ideas that help us live with greater clarity.",
    "Welcome to Atma Theory... where we ask the questions that matter most.",
]

TOPIC_TRANSITIONS: list[str] = [
    "Today's question is",
    "Today we explore",
    "Today we look at something that most of us feel but rarely name",
    "Have you ever wondered",
    "Let's understand why",
]

CLOSING_VARIATIONS: list[str] = [
    "Think deeper... live clearer.",
    "Until next time... keep questioning, keep growing.",
    "The answers you seek may already be within you.",
    "Stay curious... stay aware.",
    "See you in the next journey through Atma Theory.",
]

SOFT_CTA = (
    "If this perspective helped you see life a little differently, "
    "consider joining us for the next journey."
)


def get_welcome() -> str:
    return random.choice(WELCOME_VARIATIONS)


def get_closing() -> str:
    return random.choice(CLOSING_VARIATIONS)


def get_transition() -> str:
    return random.choice(TOPIC_TRANSITIONS)
