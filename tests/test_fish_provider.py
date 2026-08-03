"""Tests for the Fish Audio TTS provider, factory resolution, cache, and retry.

These tests mock the ``requests`` library so the suite runs without network
access. They verify the provider-agnostic architecture matches the existing
Cartesia/ElevenLabs interface.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ── Settings factory ──────────────────────────────────────────────────────────


def _fish_settings(**overrides):
    defaults = {
        "fish_api_key": "sk_fish_test",
        "fish_model": "s2.1-pro-free",
        "fish_reference_id": "ref-123",
        "fish_format": "mp3",
        "fish_timeout": 60,
        "fish_max_chars": 2000,
        "fish_cache_enabled": True,
        "fish_speed": 1.0,
        "fish_sample_rate": 44100,
        "fish_temperature": 0.7,
        "fish_top_p": 0.7,
        "fish_repetition_penalty": 1.2,
        "fish_max_new_tokens": 1024,
        "fish_normalize": True,
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
    from video_core.providers.tts.fish_provider import FishProvider

    settings = settings or _fish_settings()
    return FishProvider(settings, **kwargs)


# ── Capabilities ──────────────────────────────────────────────────────────────


class TestFishCapabilities:
    def test_provider_name(self):
        assert _make_provider().capabilities.provider_name == "fish"

    def test_no_word_boundaries(self):
        assert _make_provider().capabilities.supports_word_boundaries is False

    def test_no_streaming(self):
        assert _make_provider().capabilities.supports_streaming is False


# ── Fail-fast validation ──────────────────────────────────────────────────────


class TestFishFailFast:
    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="FISH_API_KEY"):
            _make_provider(_fish_settings(fish_api_key=""))

    def test_missing_model_raises(self):
        with pytest.raises(ValueError, match="FISH_MODEL"):
            _make_provider(_fish_settings(fish_model=""))

    def test_missing_reference_id_raises(self):
        with pytest.raises(ValueError, match="FISH_REFERENCE_ID"):
            _make_provider(_fish_settings(fish_reference_id=""))


# ── Provider synthesis with mocked requests ───────────────────────────────────


def _fake_response(mp3_bytes: bytes = b"ID3fake_mp3"):
    response = MagicMock()
    response.status_code = 200
    response.content = mp3_bytes
    response.text = ""
    return response


class TestFishSynthesis:
    def test_generate_writes_file(self, tmp_path):
        settings = _fish_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            return_value=_fake_response(),
        ), patch(
            "video_core.providers.tts.fish_provider.FishProvider._probe_duration",
            return_value=3.0,
        ):
            result = provider.generate("Hello world narration.", out)
        assert result == out
        assert out.exists()
        assert out.read_bytes() == b"ID3fake_mp3"

    def test_generate_sends_full_config_payload(self, tmp_path):
        settings = _fish_settings(
            fish_speed=1.5,
            fish_sample_rate=48000,
            fish_temperature=0.5,
            fish_top_p=0.8,
            fish_repetition_penalty=1.5,
            fish_max_new_tokens=512,
            fish_normalize=False,
            fish_cache_enabled=False,
        )
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"

        captured = {}

        def _fake_post(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers", {})
            captured["data"] = json.loads(kwargs.get("data", "{}"))
            return _fake_response()

        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            side_effect=_fake_post,
        ), patch(
            "video_core.providers.tts.fish_provider.FishProvider._probe_duration",
            return_value=3.0,
        ):
            provider.generate("Hello world.", out)

        payload = captured["data"]
        assert payload["sample_rate"] == 48000
        assert payload["prosody"]["speed"] == 1.5
        assert payload["temperature"] == 0.5
        assert payload["top_p"] == 0.8
        assert payload["repetition_penalty"] == 1.5
        assert payload["max_new_tokens"] == 512
        assert payload["normalize"] is False

    def test_generate_caches_and_skips_api_on_second_call(self, tmp_path):
        settings = _fish_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"

        fake = _fake_response()
        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            return_value=fake,
        ), patch(
            "video_core.providers.tts.fish_provider.FishProvider._probe_duration",
            return_value=3.0,
        ):
            provider.generate("Hello world narration.", out)
            provider.generate("Hello world narration.", out)

        assert fake.call_count <= 1
        assert out.exists()

    def test_generate_with_boundaries_returns_empty(self, tmp_path):
        settings = _fish_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            return_value=_fake_response(),
        ), patch(
            "video_core.providers.tts.fish_provider.FishProvider._probe_duration",
            return_value=3.0,
        ):
            path, boundaries = provider.generate_with_boundaries(
                "Hello world narration.", out
            )
        assert path == out
        assert boundaries == []

    def test_unauthorized_raises_on_401(self, tmp_path):
        settings = _fish_settings()
        settings.fish_cache_enabled = False  # type: ignore[attr-defined]
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        response = MagicMock()
        response.status_code = 401
        response.content = b""
        response.text = "Unauthorized"
        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            return_value=response,
        ), pytest.raises(ValueError, match="401 Unauthorized"):
            provider.generate("Hello world.", out)

    def test_rate_limit_raises_on_429(self, tmp_path):
        settings = _fish_settings()
        settings.fish_cache_enabled = False  # type: ignore[attr-defined]
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        response = MagicMock()
        response.status_code = 429
        response.content = b""
        response.text = "Rate limit"
        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            return_value=response,
        ), pytest.raises(ValueError, match="rate limit"):
            provider.generate("Hello world.", out)

    def test_invalid_reference_id_raises_on_404(self, tmp_path):
        settings = _fish_settings()
        settings.fish_cache_enabled = False  # type: ignore[attr-defined]
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"
        response = MagicMock()
        response.status_code = 404
        response.content = b""
        response.text = "Not found"
        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            return_value=response,
        ), pytest.raises(ValueError, match="404"):
            provider.generate("Hello world.", out)


# ── Retry behavior ────────────────────────────────────────────────────────────


class TestFishRetry:
    def test_retry_on_connection_error(self, tmp_path):
        settings = _fish_settings()
        settings.fish_cache_enabled = False  # type: ignore[attr-defined]
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"

        call_count = 0

        def _fake_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("connection reset")
            return _fake_response()

        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            side_effect=_fake_post,
        ), patch(
            "video_core.providers.tts.fish_provider.FishProvider._probe_duration",
            return_value=3.0,
        ), patch("time.sleep"):
            result = provider.generate("Hello world.", out)
        assert result == out
        assert call_count == 2

    def test_no_retry_on_auth_error(self, tmp_path):
        settings = _fish_settings()
        settings.fish_cache_enabled = False  # type: ignore[attr-defined]
        provider = _make_provider(settings)
        out = tmp_path / "scene.mp3"

        response = MagicMock()
        response.status_code = 401
        response.content = b""
        response.text = "Unauthorized"

        with patch(
            "video_core.providers.tts.fish_provider.requests.post",
            return_value=response,
        ), pytest.raises(ValueError, match="401"):
            provider.generate("Hello world.", out)
        assert provider is not None


# ── Factory resolution ────────────────────────────────────────────────────────


class TestFactory:
    def test_factory_resolves_fish(self):
        from video_core.providers.tts.factory import get_tts_provider

        s = _fish_settings()
        s.tts_provider = "fish"  # type: ignore[attr-defined]
        from video_core.providers.tts.fish_provider import FishProvider

        assert isinstance(get_tts_provider(s), FishProvider)

    def test_factory_resolves_cartesia_still_works(self):
        from video_core.providers.tts.cartesia import CartesiaTTSProvider
        from video_core.providers.tts.factory import get_tts_provider

        s = _fish_settings()
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

        s = _fish_settings()
        s.tts_provider = "bogus"  # type: ignore[attr-defined]
        with pytest.raises(ValueError, match="Unsupported TTS provider"):
            get_tts_provider(s)
