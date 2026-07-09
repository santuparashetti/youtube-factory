"""CTAOverlayConfig — all configurable parameters for the CTA Overlay Engine.

Values come from ``config/brand_config.yaml`` (``cta_overlay:`` block) and
fall back to the Atma Theory defaults when the key is absent.

Template-vs-branding precedence (from spec):
  - Templates supply structural/animation defaults (layout, motion curve, icon set).
  - The channel ``branding`` block (accent_color, font) always overrides template
    colours and typeface — unless the template property is ``locked: true``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


# ── Template registry ──────────────────────────────────────────────────────────
# Each template defines defaults that may be overridden by channel branding.
# Fields marked locked=True are intentionally NOT overridable by branding.

TEMPLATE_DEFAULTS: dict[str, dict] = {
    "glass": {
        "accent_color": "#FFFFFF",
        "font": "Arial",
        "panel_alpha": 0.25,
        "border_alpha": 0.6,
        "animation": "smooth_fade",
        "zone_default": "bottom_center",
    },
    "minimal": {
        "accent_color": "#FFFFFF",
        "font": "Arial",
        "panel_alpha": 0.0,  # no panel — just text
        "border_alpha": 0.0,
        "animation": "smooth_fade",
        "zone_default": "upper_right",
    },
    "atma": {
        "accent_color": "#2EC5E8",  # cyan/teal
        "font": "Arial",
        "panel_alpha": 0.25,
        "border_alpha": 0.8,
        "animation": "smooth_fade",
        "zone_default": "bottom_center",
    },
    "premium": {
        "accent_color": "#FFD700",  # gold
        "font": "Arial",
        "panel_alpha": 0.30,
        "border_alpha": 0.9,
        "animation": "smooth_fade",
        "zone_default": "bottom_center",
    },
}

# Backward-compat alias
TEMPLATE_DEFAULTS["atma_glass"] = TEMPLATE_DEFAULTS["atma"]


@dataclass
class CTAOverlayConfig:
    """Full configuration for one CTA overlay pass.

    Merges template defaults with channel branding per the precedence rule:
      - Template provides layout/animation structure.
      - Channel branding (accent_color, font) always wins unless ``accent_locked``
        or ``font_locked`` is True on the template (not currently set for any
        built-in template, so branding always overrides).
    """

    # ── Master switch ─────────────────────────────────────────────────────────
    enabled: bool = False

    # ── Template ──────────────────────────────────────────────────────────────
    template: str = "atma"

    # ── Timing ───────────────────────────────────────────────────────────────
    timing_mode: str = "contextual"  # "contextual" | "fixed"
    fallback_timing: float = 0.65  # fraction of video duration
    duration: float = 6.0  # seconds (full CTA target)
    min_pause_ms_for_full_cta: int = 3000  # below this → compact variant
    max_placement_search_pct: float = 0.90  # stop searching past this % of video

    # Minimum insight-tier pause duration to consider for CTA placement (ms)
    # Pauses ≥ this are "insight-tier" for CTA purposes.
    insight_tier_min_ms: int = 1800

    # ── Animation ────────────────────────────────────────────────────────────
    animation: str = "smooth_fade"
    fade_in_seconds: float = 0.8
    fade_out_seconds: float = 0.8

    # ── Content switches ──────────────────────────────────────────────────────
    show_like: bool = True
    show_subscribe: bool = True
    show_bell: bool = True

    # ── Sound ────────────────────────────────────────────────────────────────
    sound: str = "meditation_chime"  # used if assets/cta/sounds/<name>.mp3 exists

    # ── Branding (merged from channel branding block) ─────────────────────────
    accent_color: str = "#2EC5E8"
    font: str = "Arial"
    logo: str = ""

    # ── Derived template values (populated by load_cta_config) ───────────────
    panel_alpha: float = 0.25
    border_alpha: float = 0.8
    zone_default: str = "bottom_center"

    # ── BGM secondary duck ────────────────────────────────────────────────────
    # dB reduction applied to the BGM track at the CTA timestamp
    bgm_secondary_duck_db: float = 4.0


def load_cta_config(
    config_path: str | Path | None = None,
    *,
    reload: bool = False,
) -> CTAOverlayConfig:
    """Load CTA overlay config from brand_config.yaml.

    Reads the ``cta_overlay:`` block and merges template defaults with
    channel branding.  Falls back to ATma Theory defaults when absent.
    Pass ``reload=True`` to force a fresh read (useful in tests).
    """
    global _cache
    if _cache is not None and not reload:
        return _cache

    path = Path(config_path) if config_path else Path("config/brand_config.yaml")

    raw_brand: dict = {}
    raw_cta_overlay: dict = {}

    if path.exists():
        try:
            import yaml  # type: ignore[import-untyped]

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            raw_brand = data.get("branding", {})
            raw_cta_overlay = data.get("cta_overlay", {})
        except Exception:
            pass

    _cache = _parse_cta_config(raw_cta_overlay, raw_brand)
    return _cache


def reset_cta_config_cache() -> None:
    """Reset the in-memory cache.  Call this in tests that swap config files."""
    global _cache
    _cache = None


_cache: CTAOverlayConfig | None = None


# ── Internal parser ────────────────────────────────────────────────────────────


def _parse_cta_config(raw: dict, brand_raw: dict) -> CTAOverlayConfig:
    cfg = CTAOverlayConfig()

    cfg.enabled = bool(raw.get("enabled", cfg.enabled))
    cfg.template = str(raw.get("template", cfg.template))
    cfg.timing_mode = str(raw.get("timing_mode", cfg.timing_mode))

    fallback_raw = raw.get("fallback_timing", "65%")
    if isinstance(fallback_raw, str) and fallback_raw.endswith("%"):
        cfg.fallback_timing = float(fallback_raw.rstrip("%")) / 100.0
    else:
        val = float(fallback_raw) if fallback_raw else cfg.fallback_timing
        cfg.fallback_timing = val if val <= 1.0 else val / 100.0

    duration_raw = raw.get("duration", f"{cfg.duration}s")
    if isinstance(duration_raw, str) and duration_raw.endswith("s"):
        cfg.duration = float(duration_raw.rstrip("s"))
    else:
        cfg.duration = float(duration_raw) if duration_raw else cfg.duration

    cfg.min_pause_ms_for_full_cta = int(
        raw.get("min_pause_ms_for_full_cta", cfg.min_pause_ms_for_full_cta)
    )
    cfg.max_placement_search_pct = float(
        raw.get("max_placement_search_pct", cfg.max_placement_search_pct * 100) / 100.0
        if isinstance(raw.get("max_placement_search_pct"), (int, float))
        and raw.get("max_placement_search_pct", 1) > 1
        else raw.get("max_placement_search_pct", cfg.max_placement_search_pct)
    )
    cfg.insight_tier_min_ms = int(
        raw.get("insight_tier_min_ms", cfg.insight_tier_min_ms)
    )
    cfg.animation = str(raw.get("animation", cfg.animation))
    cfg.fade_in_seconds = float(raw.get("fade_in_seconds", cfg.fade_in_seconds))
    cfg.fade_out_seconds = float(raw.get("fade_out_seconds", cfg.fade_out_seconds))
    cfg.show_like = bool(raw.get("show_like", cfg.show_like))
    cfg.show_subscribe = bool(raw.get("show_subscribe", cfg.show_subscribe))
    cfg.show_bell = bool(raw.get("show_bell", cfg.show_bell))
    cfg.sound = str(raw.get("sound", cfg.sound))
    cfg.bgm_secondary_duck_db = float(
        raw.get("bgm_secondary_duck_db", cfg.bgm_secondary_duck_db)
    )

    # Apply template defaults first
    tmpl = TEMPLATE_DEFAULTS.get(cfg.template, TEMPLATE_DEFAULTS["atma"])
    cfg.accent_color = str(tmpl.get("accent_color", cfg.accent_color))
    cfg.font = str(tmpl.get("font", cfg.font))
    cfg.panel_alpha = float(tmpl.get("panel_alpha", cfg.panel_alpha))
    cfg.border_alpha = float(tmpl.get("border_alpha", cfg.border_alpha))
    cfg.zone_default = str(tmpl.get("zone_default", cfg.zone_default))

    # Branding always wins (unless template property is locked — no built-in templates lock)
    if isinstance(brand_raw, dict):
        if "accent_color" in brand_raw:
            cfg.accent_color = str(brand_raw["accent_color"])
        if "font" in brand_raw:
            cfg.font = str(brand_raw["font"])
        if "logo" in brand_raw:
            cfg.logo = str(brand_raw["logo"])

    # Inline overrides from cta_overlay block win over everything
    if "accent_color" in raw:
        cfg.accent_color = str(raw["accent_color"])
    if "font" in raw:
        cfg.font = str(raw["font"])
    if "logo" in raw:
        cfg.logo = str(raw["logo"])

    return cfg
