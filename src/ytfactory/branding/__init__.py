"""Brand Template System.

Public API:
  get_brand_config()        → BrandConfig loaded from config/brand_config.yaml
  reset_brand_config_cache() → force reload on next access (for tests)
  BrandConfig               → full brand configuration dataclass
  BrandValidator            → script placement validator
  BrandValidationReport     → validation result
"""

from ytfactory.branding.config import (
    BrandConfig,
    BrandingPlacementConfig,
    ContentSection,
    VoiceConfig,
    get_brand_config,
    reset_brand_config_cache,
)
from ytfactory.branding.validator import BrandValidationReport, BrandValidator

__all__ = [
    "BrandConfig",
    "BrandingPlacementConfig",
    "BrandValidationReport",
    "BrandValidator",
    "ContentSection",
    "VoiceConfig",
    "get_brand_config",
    "reset_brand_config_cache",
]
