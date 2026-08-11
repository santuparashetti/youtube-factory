"""Channel branding — welcome, closing, CTA, and topic transitions.

All branding content is read from config/brand_config.yaml via the Brand
Template System.  The WELCOME_VARIATIONS, CLOSING_VARIATIONS, and SOFT_CTA
constants below are computed at module load time from the brand config so that
importers (e.g. scene_planner_node) can reference them as module-level values.

To change channel branding update config/brand_config.yaml.  No code changes
are required.
"""

from __future__ import annotations

import random

from ytfactory.branding.config import get_brand_config

# -- Computed from brand config at import time ---------------------------------

_cfg = get_brand_config()

WELCOME_VARIATIONS: list[str] = [_cfg.opening.text()]

TOPIC_TRANSITIONS: list[str] = [
    "Today's question is",
    "Today we explore",
    "Today we look at something that most of us feel but rarely name",
    "Have you ever wondered",
    "Let's understand why",
]

# Both closing and signature phrases are valid triggers for the brand card.
CLOSING_VARIATIONS: list[str] = [_cfg.closing.text(), _cfg.signature.text()]

SOFT_CTA: str = _cfg.cta.text()


# -- Public API ---------------------------------------------------------------


def get_welcome() -> str:
    """Return the channel's opening welcome text."""
    return get_brand_config().opening.text()


def get_closing() -> str:
    """Return the channel's closing signature (tagline that ends the video)."""
    return get_brand_config().signature.text()


def get_closing_brand() -> str:
    """Return the channel's brand assertion placed before the CTA ('This is Atma Theory.')."""
    return get_brand_config().closing.text()


def get_cta() -> str:
    """Return the channel's call to action."""
    return get_brand_config().cta.text()


def get_transition() -> str:
    """Return a random topic-transition opener."""
    return random.choice(TOPIC_TRANSITIONS)
