"""Configuration for Publishing & Growth Engine V1."""

from __future__ import annotations

from dataclasses import dataclass, field


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
    script_excerpt_chars: int = 800  # chars of script sent to LLM prompts (non-description stages)
    scene_titles_in_prompt: int = 5  # how many scene titles to include
    description_script_chars: int = 3000  # larger window for description template generation

    # ── Description template — hashtag cap (spec: 5–8) ───────────────────────
    description_max_hashtags: int = 8

    # ── Description template — Links block (section 12) ──────────────────────
    # Order in description: Subscribe → Watch Next → Playlist → Newsletter → Socials
    # Empty strings are omitted from the output; do not fabricate links.
    subscribe_url: str = ""
    watch_next_url: str = ""
    playlist_url: str = ""
    newsletter_url: str = ""
    socials_urls: list[str] = field(default_factory=list)
