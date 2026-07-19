"""Tests for the Cartesia TTS provider, factory resolution, cache, and retry.

These tests mock the heavy `cartesia` SDK so the suite runs without network
access or the package installed. They verify the provider-agnostic architecture
matches the existing Edge/Kokoro interface and that the new shared
infrastructure (cache, retry, batching) behaves correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from video_core.providers.tts.capabilities import ProviderCapabilities
from video_core.providers.tts.infra import (
    TTSCache,
    batch_sentences,
    is_retryable,
    with_retry,
)
from video_core.providers.tts.voice_profiles import (
    Emotion,
    NarrationStyle,
    PacingProfile,
    get_voice_profile,
    list_voice_profiles,
)


# ── Settings factory ──────────────────────────────────────────────────────────


def _cartesia_settings(**overrides):
    defaults = {
        "cartesia_api_key": "sk_test",
        "cartesia_model": "sonic-3.5",
        "cartesia_voice_id": "voice-123",
        "cartesia_speed": 0.84,
        "cartesia_output_format": "wav",
        "cartesia_timeout": 60,
        "cartesia_max_chars": 2000,
        "cartesia_cache_enabled": True,
        "cartesia_pronunciation_dict_id": "",
        "cartesia_sample_rate": 44100,
        "cartesia_emotion": "calm",
        "kokoro_voice": "am_michael",
        "kokoro_speed": 0.85,
        "kokoro_sample_rate": 24000,
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
    from video_core.providers.tts.cartesia import CartesiaTTSProvider

    settings = settings or _cartesia_settings()
    return CartesiaTTSProvider(settings, **kwargs)


# ── Voice profile layer ───────────────────────────────────────────────────────


class TestVoiceProfile:
    def test_default_profile_present(self):
        assert "atma_theory" in list_voice_profiles()

    def test_atma_theory_maps_to_cartesia(self):
        p = get_voice_profile("atma_theory")
        assert p.provider == "cartesia"
        assert p.narration_style == NarrationStyle.DOCUMENTARY
        assert p.emotion == Emotion.CALM
        assert p.pacing_profile == PacingProfile.SPIRITUAL

    def test_unknown_profile_raises(self):
        with pytest.raises(ValueError, match="Unknown VOICE_PROFILE"):
            get_voice_profile("nope")

    def test_empty_name_returns_default(self):
        assert get_voice_profile("").name == "atma_theory"


# ── Capabilities ──────────────────────────────────────────────────────────────


class TestCartesiaCapabilities:
    def test_provider_name(self):
        assert _make_provider().capabilities.provider_name == "cartesia"

    def test_supports_rate_and_streaming(self):
        caps: ProviderCapabilities = _make_provider().capabilities
        assert caps.supports_rate is True
        assert caps.supports_streaming is True
        assert caps.supports_emotion is True

    def test_no_word_boundaries(self):
        assert _make_provider().capabilities.supports_word_boundaries is False


# ── Fail-fast validation (Step 9) ────────────────────────────────────────────


class TestCartesiaFailFast:
    def test_missing_api_key_raises(self):
        with pytest.raises(ValueError, match="CARTESIA_API_KEY"):
            _make_provider(_cartesia_settings(cartesia_api_key=""))

    def test_missing_model_raises(self):
        with pytest.raises(ValueError, match="CARTESIA_MODEL"):
            _make_provider(_cartesia_settings(cartesia_model=""))

    def test_missing_voice_id_raises(self):
        with pytest.raises(ValueError, match="CARTESIA_VOICE_ID"):
            _make_provider(_cartesia_settings(cartesia_voice_id=""))


# ── Retry policy (Step 8) ────────────────────────────────────────────────────


class TestRetryPolicy:
    def test_no_retry_on_401(self):
        assert is_retryable(ValueError("401 Unauthorized")) is False

    def test_no_retry_on_403(self):
        assert is_retryable(RuntimeError("403 Forbidden")) is False

    def test_no_retry_on_404(self):
        assert is_retryable(ValueError("404 Not Found")) is False

    def test_no_retry_on_invalid_request(self):
        assert is_retryable(ValueError("Invalid request: bad voice id")) is False

    def test_no_retry_on_auth_error(self):
        assert is_retryable(RuntimeError("Authentication failed")) is False

    def test_retry_on_timeout(self):
        assert is_retryable(TimeoutError("took too long")) is True

    def test_retry_on_connection_reset(self):
        assert is_retryable(ConnectionError("Connection reset by peer")) is True

    def test_retry_on_oserror(self):
        assert is_retryable(OSError("network unreachable")) is True

    def test_retry_only_transient_then_succeeds(self, tmp_path):
        calls = {"n": 0}

        def action():
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("slow")
            return None

        with patch("time.sleep"):
            with_retry(action, max_retries=2, timeout=60)
        assert calls["n"] == 2

    def test_retry_stops_on_auth_error(self):
        with pytest.raises(ValueError, match="401"):
            with_retry(
                lambda: (_ for _ in ()).throw(ValueError("401 Unauthorized")),
                max_retries=3,
                timeout=60,
            )


# ── Cache (Step 6) ────────────────────────────────────────────────────────────


class TestTTSCache:
    def test_key_is_deterministic(self):
        k1 = TTSCache.make_key(
            text="hello", voice_id="v", model="m", speed=0.84, output_format="wav"
        )
        k2 = TTSCache.make_key(
            text="hello", voice_id="v", model="m", speed=0.84, output_format="wav"
        )
        assert k1 == k2

    def test_key_changes_with_speed(self):
        k1 = TTSCache.make_key(text="hello", voice_id="v", model="m", speed=0.84, output_format="wav")
        k2 = TTSCache.make_key(text="hello", voice_id="v", model="m", speed=1.0, output_format="wav")
        assert k1 != k2

    def test_put_then_get(self, tmp_path):
        cache = TTSCache(cache_dir=tmp_path, enabled=True)
        key = "abc"
        cache.put(key, "wav", b"RIFFdata")
        assert cache.get(key, "wav") is not None

    def test_disabled_cache_returns_none(self, tmp_path):
        cache = TTSCache(cache_dir=tmp_path, enabled=False)
        assert cache.get("anything", "wav") is None

    def test_copy_to_writes_file(self, tmp_path):
        cache = TTSCache(cache_dir=tmp_path / "c", enabled=True)
        cache.put("k", "wav", b"XYZ")
        dest = tmp_path / "out.wav"
        assert cache.copy_to("k", "wav", dest) is True
        assert dest.read_bytes() == b"XYZ"


# ── Sentence batching (Step 5) ───────────────────────────────────────────────


class TestBatching:
    def test_single_short_text_one_batch(self):
        batches = batch_sentences("Short text here.", max_chars=2000, min_chars=1500)
        assert len(batches) == 1

    def test_long_text_splits_near_target(self):
        text = "Sentence about the universe and our place within it. " * 120
        batches = batch_sentences(text, max_chars=2000, min_chars=1500)
        # No batch should exceed the max; most should be near the target.
        assert all(len(b) <= 2000 for b in batches)
        # A final remainder may exist but must never be a tiny orphan (< 100 chars).
        if len(batches) > 1:
            assert len(batches[-1]) >= 100

    def test_paragraph_boundaries_preserved(self):
        text = "First paragraph about stillness.\n\nSecond paragraph about peace."
        batches = batch_sentences(text, max_chars=2000, min_chars=1500)
        # Joined batch should still contain the paragraph break marker words.
        joined = " ".join(batches)
        assert "stillness" in joined and "peace" in joined


# ── Provider synthesis with mocked client ─────────────────────────────────────


def _fake_client(wav_bytes: bytes = b"RIFFfakewav"):
    """Build a fake Cartesia client whose tts.bytes returns a chunk generator."""
    client = MagicMock()
    client.tts.bytes.return_value = iter([wav_bytes, b"", wav_bytes])
    return client


class TestCartesiaSynthesis:
    def test_generate_writes_file(self, tmp_path):
        settings = _cartesia_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.wav"
        with patch.object(
            provider, "_get_client", return_value=_fake_client()
        ), patch(
            "video_core.providers.tts.cartesia.CartesiaTTSProvider._probe_duration",
            return_value=3.0,
        ):
            result = provider.generate("Hello world narration.", out)
        assert result == out
        assert out.exists()

    def test_generate_caches_and_skips_api_on_second_call(self, tmp_path):
        settings = _cartesia_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.wav"

        fake = _fake_client()
        with patch.object(provider, "_get_client", return_value=fake), patch(
            "video_core.providers.tts.cartesia.CartesiaTTSProvider._probe_duration",
            return_value=3.0,
        ):
            provider.generate("Hello world narration.", out)
            # Second request with identical text hits the cache — no new API call.
            provider.generate("Hello world narration.", out)

        # Cache hit short-circuits BEFORE the API call: identical text never
        # triggers a second Cartesia request (SDK invoked at most once total).
        assert fake.tts.bytes.call_count <= 1
        assert out.exists()

    def test_generate_with_boundaries_returns_empty(self, tmp_path):
        settings = _cartesia_settings()
        provider = _make_provider(settings)
        out = tmp_path / "scene.wav"
        with patch.object(
            provider, "_get_client", return_value=_fake_client()
        ), patch(
            "video_core.providers.tts.cartesia.CartesiaTTSProvider._probe_duration",
            return_value=3.0,
        ):
            path, boundaries = provider.generate_with_boundaries(
                "Hello world narration.", out
            )
        assert path == out
        assert boundaries == []


# ── Factory resolution (Step 4) ──────────────────────────────────────────────


class TestFactory:
    def test_factory_resolves_cartsia(self):
        from video_core.providers.tts.cartesia import CartesiaTTSProvider
        from video_core.providers.tts.factory import get_tts_provider

        s = _cartesia_settings()
        s.tts_provider = "cartesia"  # type: ignore[attr-defined]
        s.voice_profile = "atma_theory"  # type: ignore[attr-defined]
        assert isinstance(get_tts_provider(s), CartesiaTTSProvider)

    def test_factory_resolves_kokoro(self):
        from video_core.providers.tts.kokoro import KokoroProvider
        from video_core.providers.tts.factory import get_tts_provider

        s = _cartesia_settings()
        s.tts_provider = "kokoro"  # type: ignore[attr-defined]
        assert isinstance(get_tts_provider(s), KokoroProvider)

    def test_factory_unknown_raises(self):
        from video_core.providers.tts.factory import get_tts_provider

        s = _cartesia_settings()
        s.tts_provider = "bogus"  # type: ignore[attr-defined]
        with pytest.raises(ValueError, match="Unsupported TTS provider"):
            get_tts_provider(s)
