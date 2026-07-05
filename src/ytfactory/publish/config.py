"""Configuration for Publishing & Growth Engine V1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PublishConfig:
    """All tunable knobs for the Publishing & Growth Engine V1."""

    # ── Thumbnail ─────────────────────────────────────────────────────────────
    thumbnail_width: int = 1280  # YouTube recommended thumbnail width
    thumbnail_height: int = 720  # YouTube recommended thumbnail height
    thumbnail_variants: int = 3  # number of A/B thumbnail variants to generate

    # Set True to skip image API calls (useful in CI or when no image key)
    skip_thumbnail: bool = False

    # ── Title ─────────────────────────────────────────────────────────────────
    max_title_length: int = 100  # YouTube hard limit
    optimal_title_length: int = 70  # CTR sweet spot

    # ── Description ──────────────────────────────────────────────────────────
    max_description_length: int = 5000  # YouTube hard limit

    # ── SEO / Tags ────────────────────────────────────────────────────────────
    max_tags_chars: int = 500  # YouTube tag character budget
    max_hashtags: int = 15  # YouTube limit for clickable hashtags
    max_keywords: int = 30  # total keyword list cap

    # ── Script context ────────────────────────────────────────────────────────
    script_excerpt_chars: int = 800  # chars of script sent to LLM prompts
    scene_titles_in_prompt: int = 5  # how many scene titles to include
