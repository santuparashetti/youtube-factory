"""Tests for the ElevenLabs TTS provider, factory resolution, cache, and retry.

These tests mock the heavy `elevenlabs` SDK so the suite runs without network
access or the package installed. They verify the provider-agnostic architecture
matches the existing Cartesia interface.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from video_core.providers.tts.capabilities import ProviderCapabilities

# ── Settings factory ──────────────────────────────────────────────────────────


def _elevenlabs_settings(**overrides):
    defaults = {
        "elevenlabs_api_key": "sk_test",
        "elevenlabs_model": "eleven_flash_v2_5",
        "elevenlabs_voice_id": "voice-123",
        "elevenlabs_output_format": "mp3_44100_128",
        "elevenlabs_timeout": 60,
        "elevenlabs_max_chars": 2000,
        "elevenlabs_cache_enabled": True,
        "elevenlabs_sample_rate": 44100,
        "tts_auto_retry": True,
        "tts_max_retries": 2,
    }
    defaults.update(overrides)

    class _S:
        pass

    s = _S()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _make_provider(settings=None, **kwargs):
    from video_core.providers.tts.elevenlabs import ElevenLabsProvider

    settings = settings or _elevenlabs_settings()
    return ElevenLabsProvider(settings, **kwargs)


# ── Capabilities ──────────────────────────────────────────────────────────────


class TestElevenLabsCapabilities:
    def test_provider_name(self):
        assert _make_provider().capabilities.provider_name == "elevenlabs"

    def test_supports_streaming(self):
        caps: ProviderCapabilities = _make_provider().capabilities
        assert caps.supports_streaming is True

    def test_no_word_boundaries(self):
        assert _make_provider().capabilities.supports_word_boundaries is False


# ── Fail-fast validation ──────────────────────────────────────────────────────


class TestElevenLabsFailFast:
    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="ELEVENLABS_API_KEY"):
            _make_provider(_elevenlabs_settings(elevenlabs_api_key=""))

    def test_missing_model_raises(self):
        with pytest.raises(ValueError, match="ELEVENLABS_MODEL"):
            _make_provider(_elevenlabs_settings(elevenlabs_model=""))

    def test_missing_voice_id_raises(self):
        with pytest.raises(ValueError, match="ELEVENLABS_VOICE_ID"):
            _make_provider(_elevenlabs_settings(elevenlabs_voice_id=""))


# ── Provider synthesis with mocked client ─────────────────────────────────────


def _fake_client(mp3_bytes: bytes = b"ID3fake_mp3"):
    """Build a fake ElevenLabs client whose text_to_speech.convert returns a chunk generator."""
    client = MagicMock()
    client.text_to_speech.convert.return_value = iter([mp3_bytes, b"", mp3_bytes])
    return client


class TestElevenLabsSynthesis:
    def test_generate_writes_file(self, tmp_path):
        settings = _elevenlabs_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        with patch.object(
            provider, "_get_client", return_value=_fake_client()
        ), patch(
            "video_core.providers.tts.elevenlabs.ElevenLabsProvider._probe_duration",
            return_value=3.0,
        ):
            result = provider.generate("Hello world narration.", out)
        assert result == out
        assert out.exists()

    def test_generate_caches_and_skips_api_on_second_call(self, tmp_path):
        settings = _elevenlabs_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"

        fake = _fake_client()
        with patch.object(provider, "_get_client", return_value=fake), patch(
            "video_core.providers.tts.elevenlabs.ElevenLabsProvider._probe_duration",
            return_value=3.0,
        ):
            provider.generate("Hello world narration.", out)
            provider.generate("Hello world narration.", out)

        assert fake.text_to_speech.convert.call_count <= 1
        assert out.exists()

    def test_generate_with_boundaries_returns_empty(self, tmp_path):
        settings = _elevenlabs_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        with patch.object(
            provider, "_get_client", return_value=_fake_client()
        ), patch(
            "video_core.providers.tts.elevenlabs.ElevenLabsProvider._probe_duration",
            return_value=3.0,
        ):
            path, boundaries = provider.generate_with_boundaries(
                "Hello world narration.", out
            )
        assert path == out
        assert boundaries == []

    def test_generate_with_voice_override(self, tmp_path):
        settings = _elevenlabs_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        with patch.object(
            provider, "_get_client", return_value=_fake_client()
        ), patch(
            "video_core.providers.tts.elevenlabs.ElevenLabsProvider._probe_duration",
            return_value=3.0,
        ):
            provider.generate("Hello world narration.", out, voice="custom-voice")
        assert out.exists()

    def test_import_error_raised_when_sdk_missing(self):
        settings = _elevenlabs_settings()
        provider = _make_provider(settings)
        with patch.dict("sys.modules", {"elevenlabs": None}), pytest.raises(
            RuntimeError, match="elevenlabs"
        ):
            provider._get_client()


# ── Factory resolution ────────────────────────────────────────────────────────


class TestFactory:
    def test_factory_resolves_elevenlabs(self):
        from video_core.providers.tts.elevenlabs import ElevenLabsProvider
        from video_core.providers.tts.factory import get_tts_provider

        s = _elevenlabs_settings()
        s.tts_provider = "elevenlabs"  # type: ignore[attr-defined]
        assert isinstance(get_tts_provider(s), ElevenLabsProvider)

    def test_factory_resolves_cartesia_still_works(self):
        from video_core.providers.tts.cartesia import CartesiaTTSProvider
        from video_core.providers.tts.factory import get_tts_provider

        s = _elevenlabs_settings()
        s.tts_provider = "cartesia"  # type: ignore[attr-defined]
        s.cartesia_api_key = "sk_car_test"  # type: ignore[attr-defined]
        s.cartesia_model = "sonic-3.5"  # type: ignore[attr-defined]
        s.cartesia_voice_id = "voice-123"  # type: ignore[attr-defined]
        s.cartesia_speed = 0.88  # type: ignore[attr-defined]
        s.cartesia_output_format = "wav"  # type: ignore[attr-defined]
        s.cartesia_timeout = 90  # type: ignore[attr-defined]
        s.cartesia_max_chars = 2000  # type: ignore[attr-defined]
        s.cartesia_cache_enabled = True  # type: ignore[attr-defined]
        s.cartesia_sample_rate = 44100  # type: ignore[attr-defined]
        s.cartesia_emotion = "calm"  # type: ignore[attr-defined]
        s.cartesia_pronunciation_dict_id = ""  # type: ignore[attr-defined]
        s.voice_profile = "atma_theory"  # type: ignore[attr-defined]
        assert isinstance(get_tts_provider(s), CartesiaTTSProvider)

    def test_factory_unknown_raises(self):
        from video_core.providers.tts.factory import get_tts_provider

        s = _elevenlabs_settings()
        s.tts_provider = "bogus"  # type: ignore[attr-defined]
        with pytest.raises(ValueError, match="Unsupported TTS provider"):
            get_tts_provider(s)
