"""
ProviderCapabilities — declarative feature flags for TTS providers.

Each provider advertises what it supports so callers can adapt behavior
without hardcoding provider-specific checks in business logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    """Immutable capability record for a TTS provider."""

    provider_name: str

    # Text markup
    supports_ssml: bool = False  # Accepts SSML tags in input text
    supports_voice_styles: bool = False  # Supports style= attribute in SSML

    # Prosody control
    supports_pitch: bool = False  # Rate / pitch parameters accepted
    supports_rate: bool = False

    # Output features
    supports_word_boundaries: bool = False  # Returns per-word timing events
    supports_streaming: bool = False  # Audio arrives in chunks (not one blob)

    # Emotion / style
    supports_emotion: bool = False  # Emotion-aware voice selection or SSML
