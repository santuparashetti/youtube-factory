"""TTS provider pricing abstraction.

Do NOT hardcode provider pricing. Load from configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from video_core.providers.tts.analytics.models import TTSProviderPricing


@dataclass
class ProviderPricingConfig:
    """Configuration container for TTS provider pricing."""

    providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProviderPricingConfig:
        return cls(providers=data.get("providers", {}))

    def get_pricing(self, provider_name: str) -> TTSProviderPricing:
        data = self.providers.get(provider_name.lower(), {})
        return TTSProviderPricing(
            provider_name=provider_name.lower(),
            credits_per_character=float(data.get("credits_per_character", 0.0)),
            credits_per_request=float(data.get("credits_per_request", 0.0)),
            usd_per_credit=float(data.get("usd_per_credit", 0.0)),
        )


def get_default_pricing() -> ProviderPricingConfig:
    """Return default pricing loaded from configuration.

    Cartesia pricing comes only from configuration.
    """
    import os

    providers: dict[str, dict[str, str]] = {}
    prefix = "TTS_PRICING_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            parts = key[len(prefix):].split("_", 1)
            if len(parts) == 2:
                provider, field_name = parts
                provider = provider.lower()
                if provider not in providers:
                    providers[provider] = {}
                providers[provider][field_name] = value

    return ProviderPricingConfig.from_dict({"providers": providers})
