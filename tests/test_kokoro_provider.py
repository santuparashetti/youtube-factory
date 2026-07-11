"""Tests for KokoroProvider TTS provider.

All tests mock the 'kokoro', 'soundfile', and 'numpy' heavy dependencies
so the test suite runs without a GPU or ML runtime installed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.providers.tts.capabilities import ProviderCapabilities


# ── Settings factory ──────────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Return a minimal Settings-like object for Kokoro tests."""
    defaults = {
        "kokoro_voice": "am_michael",
        "kokoro_language": "en-US",
        "kokoro_speed": 1.0,
        "kokoro_sample_rate": 24000,
        "tts_auto_retry": False,
        "tts_max_retries": 1,
    }
    defaults.update(overrides)

    class _FakeSettings:
        pass

    s = _FakeSettings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_provider(**settings_overrides):
    """Return a KokoroProvider with mocked settings."""
    from ytfactory.providers.tts.kokoro import KokoroProvider

    return KokoroProvider(_make_settings(**settings_overrides))


# ── Capabilities ──────────────────────────────────────────────────────────────


class TestKokoroCapabilities:
    def test_provider_name(self):
        p = _make_provider()
        assert p.capabilities.provider_name == "kokoro"

    def test_no_ssml(self):
        p = _make_provider()
        assert p.capabilities.supports_ssml is False

    def test_no_word_boundaries_declared(self):
        p = _make_provider()
        assert p.capabilities.supports_word_boundaries is False

    def test_supports_rate(self):
        p = _make_provider()
        assert p.capabilities.supports_rate is True

    def test_returns_provider_capabilities_instance(self):
        p = _make_provider()
        assert isinstance(p.capabilities, ProviderCapabilities)


# ── Language mapping ──────────────────────────────────────────────────────────


class TestKokoroLangMap:
    def test_en_us_maps_to_a(self):
        p = _make_provider()
        assert p._resolve_lang_code("en-US") == "a"

    def test_en_gb_maps_to_b(self):
        p = _make_provider()
        assert p._resolve_lang_code("en-GB") == "b"

    def test_bare_en_maps_to_a(self):
        p = _make_provider()
        assert p._resolve_lang_code("en") == "a"

    def test_unknown_falls_back_to_a(self):
        p = _make_provider()
        assert p._resolve_lang_code("xx-UNKNOWN") == "a"


# ── Voice resolution ──────────────────────────────────────────────────────────


class TestKokoroVoiceResolution:
    def test_default_voice_from_settings(self):
        p = _make_provider(kokoro_voice="am_michael")
        assert p._resolve_voice(None) == "am_michael"

    def test_override_voice(self):
        p = _make_provider(kokoro_voice="am_michael")
        assert p._resolve_voice("af_sarah") == "af_sarah"


# ── _get_pipeline (lazy import) ───────────────────────────────────────────────


class TestKokoroPipelineLazyImport:
    def test_raises_runtime_error_without_kokoro(self):
        """When the kokoro package is missing, a clear RuntimeError is raised."""
        p = _make_provider()
        # Temporarily hide kokoro from imports
        with patch.dict(sys.modules, {"kokoro": None}):
            with pytest.raises(RuntimeError, match="kokoro"):
                p._get_pipeline("a")

    def test_loads_kpipeline_on_first_call(self):
        """_get_pipeline calls KPipeline(lang_code=...) once and caches it."""
        mock_pipeline = MagicMock()
        mock_kpipeline_cls = MagicMock(return_value=mock_pipeline)
        mock_kokoro_mod = MagicMock()
        mock_kokoro_mod.KPipeline = mock_kpipeline_cls

        with patch.dict(sys.modules, {"kokoro": mock_kokoro_mod}):
            p = _make_provider()
            result = p._get_pipeline("a")

        mock_kpipeline_cls.assert_called_once_with(lang_code="a", repo_id="hexgrad/Kokoro-82M")
        assert result is mock_pipeline

    def test_caches_pipeline_on_second_call(self):
        """_get_pipeline reuses the already-loaded pipeline."""
        mock_pipeline = MagicMock()
        mock_kpipeline_cls = MagicMock(return_value=mock_pipeline)
        mock_kokoro_mod = MagicMock()
        mock_kokoro_mod.KPipeline = mock_kpipeline_cls

        with patch.dict(sys.modules, {"kokoro": mock_kokoro_mod}):
            p = _make_provider()
            p._get_pipeline("a")
            p._get_pipeline("a")

        assert mock_kpipeline_cls.call_count == 1


# ── _wav_to_mp3 ───────────────────────────────────────────────────────────────


class TestWavToMp3:
    def test_calls_ffmpeg(self, tmp_path):
        p = _make_provider()
        wav = tmp_path / "test.wav"
        mp3 = tmp_path / "test.mp3"
        wav.write_bytes(b"\x00" * 100)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            p._wav_to_mp3(wav, mp3)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert str(wav) in cmd
        assert str(mp3) in cmd

    def test_propagates_subprocess_error(self, tmp_path):
        p = _make_provider()
        wav = tmp_path / "test.wav"
        mp3 = tmp_path / "test.mp3"

        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
            with pytest.raises(subprocess.CalledProcessError):
                p._wav_to_mp3(wav, mp3)


# ── generate() ───────────────────────────────────────────────────────────────


class TestKokoroGenerate:
    def _mock_synthesise(self, provider, output_path: Path) -> None:
        """Patch _synthesise to write a dummy file instead of calling kokoro."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\xff\xfb" + b"\x00" * 100)

    def test_generate_returns_output_path(self, tmp_path):
        p = _make_provider()
        out = tmp_path / "scene-001.mp3"

        with patch.object(p, "_synthesise", side_effect=lambda t, o, v, lc: self._mock_synthesise(p, o)):
            result = p.generate("Hello world", out, language="en-US")

        assert result == out

    def test_generate_creates_file(self, tmp_path):
        p = _make_provider()
        out = tmp_path / "scene-001.mp3"

        with patch.object(p, "_synthesise", side_effect=lambda t, o, v, lc: self._mock_synthesise(p, o)):
            p.generate("Hello world", out, language="en-US")

        assert out.exists()

    def test_generate_with_boundaries_returns_empty_boundaries(self, tmp_path):
        p = _make_provider()
        out = tmp_path / "scene-001.mp3"

        with patch.object(p, "_synthesise", side_effect=lambda t, o, v, lc: self._mock_synthesise(p, o)):
            path, boundaries = p.generate_with_boundaries("Hello world", out, language="en-US")

        assert path == out
        assert boundaries == []

    def test_generate_retries_on_failure_then_succeeds(self, tmp_path):
        """When synthesis fails once but succeeds on the second attempt, the result is OK."""
        p = _make_provider(tts_auto_retry=True, tts_max_retries=2)
        out = tmp_path / "scene-001.mp3"

        call_count = {"n": 0}

        def _sometimes_fail(text, output_path, voice, lang_code):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient error")
            self._mock_synthesise(p, output_path)

        with patch.object(p, "_synthesise", side_effect=_sometimes_fail):
            with patch("time.sleep"):  # skip actual backoff delay
                result = p.generate("Hello", out, language="en-US")

        assert result == out
        assert call_count["n"] == 2

    def test_generate_raises_after_all_retries_exhausted(self, tmp_path):
        p = _make_provider(tts_auto_retry=True, tts_max_retries=2)
        out = tmp_path / "scene-001.mp3"

        with patch.object(p, "_synthesise", side_effect=RuntimeError("always fail")):
            with patch("time.sleep"):
                with pytest.raises(RuntimeError, match="always fail"):
                    p.generate("Hello", out, language="en-US")


# ── Factory registration ───────────────────────────────────────────────────────


class TestKokoroFactoryRegistration:
    def test_factory_returns_kokoro_provider(self):
        """get_tts_provider('kokoro') returns a KokoroProvider instance."""
        from ytfactory.providers.tts.factory import get_tts_provider
        from ytfactory.providers.tts.kokoro import KokoroProvider

        settings = _make_settings()
        settings.tts_provider = "kokoro"  # type: ignore[attr-defined]

        provider = get_tts_provider(settings)
        assert isinstance(provider, KokoroProvider)
