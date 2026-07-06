"""Brand Template System — configuration loader.

Reads config/brand_config.yaml from the project root (CWD).
Falls back to Atma Theory defaults when the file is not present,
ensuring backward compatibility with existing projects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_PATH = "config/brand_config.yaml"

# -- Default values (backward-compatible Atma Theory branding) -----------------

_DEFAULT_OPENING = "Welcome to Atma Theory... where ancient wisdom meets modern life."
_DEFAULT_CLOSING = "This is Atma Theory."
_DEFAULT_CTA = (
    "If this reflection stayed with you, consider joining us on this journey."
)
_DEFAULT_SIGNATURE = "Think deeper... Live clearer."

# -- Data models ---------------------------------------------------------------


@dataclass
class ContentSection:
    """A single piece of branded content with an enable/disable flag."""

    enabled: bool = True
    template: str = ""

    def text(self) -> str:
        """Return the template as a clean single-line string."""
        return " ".join(
            line.strip() for line in self.template.strip().splitlines() if line.strip()
        )


@dataclass
class VoiceConfig:
    """Voice pacing settings for brand sections."""

    pace: str = "calm"
    pause_after_opening_ms: int = 800
    pause_after_closing_ms: int = 1000


@dataclass
class BrandingPlacementConfig:
    """Controls where and how brand elements are placed in the video."""

    opening_position: str = "after_hook"
    closing_position: str = "before_final_quote"
    max_opening_seconds: int = 10
    asset_path: str = "assets/branding/atma-theory-brand.png"
    asset_animation: str = "slow_zoom"


@dataclass
class BrandConfig:
    """Full brand configuration for one channel.

    Sections:
      opening   — welcome shown immediately after the hook
      closing   — brand name assertion before the CTA
      cta       — call to action
      signature — final tagline that ends the video
      voice     — TTS pacing for brand sections
      branding  — placement rules and asset references
    """

    channel_name: str = "Atma Theory"
    opening: ContentSection = field(
        default_factory=lambda: ContentSection(template=_DEFAULT_OPENING)
    )
    closing: ContentSection = field(
        default_factory=lambda: ContentSection(template=_DEFAULT_CLOSING)
    )
    cta: ContentSection = field(
        default_factory=lambda: ContentSection(template=_DEFAULT_CTA)
    )
    signature: ContentSection = field(
        default_factory=lambda: ContentSection(template=_DEFAULT_SIGNATURE)
    )
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    branding: BrandingPlacementConfig = field(default_factory=BrandingPlacementConfig)


# -- Loader --------------------------------------------------------------------

_cache: BrandConfig | None = None


def get_brand_config(
    config_path: str | Path | None = None,
    *,
    reload: bool = False,
) -> BrandConfig:
    """Load and cache the brand configuration.

    Reads ``config/brand_config.yaml`` from CWD by default.
    Falls back to Atma Theory defaults when the file is absent.
    Pass ``reload=True`` to force a fresh read (useful in tests).
    """
    global _cache
    if _cache is not None and not reload:
        return _cache

    path = Path(config_path) if config_path else Path(_CONFIG_PATH)
    if not path.exists():
        _cache = BrandConfig()
        return _cache

    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        _cache = BrandConfig()
        return _cache

    _cache = _parse_brand_config(data)
    return _cache


def reset_brand_config_cache() -> None:
    """Reset the in-memory cache.  Call this in tests that swap config files."""
    global _cache
    _cache = None


# -- Internal parser -----------------------------------------------------------


def _parse_section(raw: object, default_template: str) -> ContentSection:
    if isinstance(raw, dict):
        return ContentSection(
            enabled=bool(raw.get("enabled", True)),
            template=str(raw.get("template", default_template)),
        )
    return ContentSection(template=default_template)


def _parse_voice(raw: object) -> VoiceConfig:
    if not isinstance(raw, dict):
        return VoiceConfig()
    return VoiceConfig(
        pace=str(raw.get("pace", "calm")),
        pause_after_opening_ms=int(raw.get("pause_after_opening_ms", 800)),
        pause_after_closing_ms=int(raw.get("pause_after_closing_ms", 1000)),
    )


def _parse_placement(raw: object) -> BrandingPlacementConfig:
    if not isinstance(raw, dict):
        return BrandingPlacementConfig()
    return BrandingPlacementConfig(
        opening_position=str(raw.get("opening_position", "after_hook")),
        closing_position=str(raw.get("closing_position", "before_final_quote")),
        max_opening_seconds=int(raw.get("max_opening_seconds", 10)),
        asset_path=str(raw.get("asset_path", "assets/branding/atma-theory-brand.png")),
        asset_animation=str(raw.get("asset_animation", "slow_zoom")),
    )


def _parse_brand_config(data: dict) -> BrandConfig:
    return BrandConfig(
        channel_name=str(data.get("channel_name", "Atma Theory")),
        opening=_parse_section(data.get("opening"), _DEFAULT_OPENING),
        closing=_parse_section(data.get("closing"), _DEFAULT_CLOSING),
        cta=_parse_section(data.get("cta"), _DEFAULT_CTA),
        signature=_parse_section(data.get("signature"), _DEFAULT_SIGNATURE),
        voice=_parse_voice(data.get("voice")),
        branding=_parse_placement(data.get("branding")),
    )
