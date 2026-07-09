"""CTA Overlay Engine V2 — configuration-driven, brand-aware call-to-action overlays."""

from .config import CTAOverlayConfig, load_cta_config
from .models import CTAPlacement, CTAResult, CTAReviewResult, CTAVariant, PlacementPath
from .pipeline import CTAPipeline

__all__ = [
    "CTAOverlayConfig",
    "load_cta_config",
    "CTAPlacement",
    "CTAResult",
    "CTAReviewResult",
    "CTAVariant",
    "PlacementPath",
    "CTAPipeline",
]
