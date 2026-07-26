"""Tests for TTS_SKIP_EXISTING — file-level cache check before the paid TTS
call, so re-running Phase 1 against the same script doesn't re-spend
Cartesia credits when a scene's audio already exists on disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.whisperx_enabled = False
    s.tts_auto_retry = False
    s.tts_max_retries = 1
    s.tts_validate_audio = False
    s.tts_debug = False
    s.tts_pacing_enabled = False
    s.tts_pacing_profile = "balanced"
    s.tts_analytics_enabled = True
    s.tts_log_per_scene = False
    s.tts_summary_enabled = False
    s.tts_skip_existing = True
    s.cartesia_credits_per_character = 0.0
    s.cartesia_credits_per_request = 0.0
    s.cartesia_usd_per_credit = 0.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@pytest.fixture()
def project_dir(tmp_path) -> Path:
    project_id = "test-proj"
    p = tmp_path / "workspace" / "jobs" / project_id
    (p / "scenes").mkdir(parents=True)
    (p / "audio").mkdir(parents=True)
    scene_plan = {
        "scenes": [
            {
                "index": 1,
                "title": "Opening",
                "narration": "From childhood we are taught to be good.",
                "visual_prompt": "A scenic view",
                "duration_seconds": 5.0,
                "scene_type": "generated_image",
            }
        ]
    }
    (p / "scenes" / "scene-plan.json").write_text(json.dumps(scene_plan), encoding="utf-8")
    return tmp_path


def _run_pipeline(tmp_path, settings, project_id="test-proj"):
    from ytfactory.voice.pipeline import VoicePipeline

    mock_provider = MagicMock()
    mock_provider.capabilities.provider_name = "cartesia"

    def _fake_generate(text, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\xff\xfb" + b"\x00" * 2000)
        return output_path, []

    mock_provider.generate_with_boundaries.side_effect = _fake_generate

    orig = os.getcwd()
    os.chdir(tmp_path)
    try:
        with patch("ytfactory.voice.pipeline.get_tts_provider", return_value=mock_provider), \
             patch("ytfactory.voice.pipeline._normalize_audio_attack"), \
             patch("ytfactory.voice.pipeline.VoiceRepository"), \
             patch("ytfactory.voice.pipeline.TTSDebugWriter"):
            pipeline = VoicePipeline(settings)
            pipeline._provider = mock_provider
            pipeline.run(project_id)
            return pipeline, mock_provider
    finally:
        os.chdir(orig)


class TestSkipExistingAudio:
    def test_skips_provider_call_when_audio_exists_and_valid(self, project_dir):
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 2000)
        # timing.json deliberately absent — simulates an interrupted prior run

        settings = _settings()
        pipeline, mock_provider = _run_pipeline(project_dir, settings)

        mock_provider.generate_with_boundaries.assert_not_called()
        assert (audio_dir / "scene-001.timing.json").exists()

    def test_still_calls_provider_when_file_too_small(self, project_dir):
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "scene-001.mp3").write_bytes(b"\x00" * 10)  # < 1000 bytes

        settings = _settings()
        pipeline, mock_provider = _run_pipeline(project_dir, settings)

        mock_provider.generate_with_boundaries.assert_called_once()

    def test_disabled_setting_still_calls_provider(self, project_dir):
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 2000)

        settings = _settings(tts_skip_existing=False)
        pipeline, mock_provider = _run_pipeline(project_dir, settings)

        mock_provider.generate_with_boundaries.assert_called_once()

    def test_no_audio_file_calls_provider_normally(self, project_dir):
        settings = _settings()
        pipeline, mock_provider = _run_pipeline(project_dir, settings)
        mock_provider.generate_with_boundaries.assert_called_once()

    def test_skip_records_cache_hit_analytics(self, project_dir):
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 2000)

        settings = _settings()
        pipeline, _ = _run_pipeline(project_dir, settings)

        records = pipeline._analytics.all_records()
        assert len(records) == 1
        assert records[0].cache_hit is True


class TestSubtitleRegeneration:
    def test_subtitles_regenerated_when_missing_even_if_tts_cached(self, project_dir):
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 2000)
        # timing.json is missing

        settings = _settings()
        with patch("ytfactory.voice.pipeline._get_audio_duration", return_value=5.0):
            pipeline, mock_provider = _run_pipeline(project_dir, settings)

        mock_provider.generate_with_boundaries.assert_not_called()
        assert (audio_dir / "scene-001.timing.json").exists()

    def test_subtitles_skipped_when_already_exist(self, project_dir):
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 2000)
        (audio_dir / "scene-001.timing.json").write_text("[{}]", encoding="utf-8")

        settings = _settings()
        pipeline, mock_provider = _run_pipeline(project_dir, settings)

        mock_provider.generate_with_boundaries.assert_not_called()

    def test_tts_and_subtitle_independent(self, project_dir):
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        # Case 1: TTS cached + subtitle missing → subtitle regenerated
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 2000)
        settings = _settings()
        with patch("ytfactory.voice.pipeline._get_audio_duration", return_value=5.0):
            pipeline, mock_provider = _run_pipeline(project_dir, settings)
        mock_provider.generate_with_boundaries.assert_not_called()
        assert (audio_dir / "scene-001.timing.json").exists()

        # Case 2: TTS cached + subtitle exists → both skipped
        (audio_dir / "scene-001.timing.json").write_text("[{}]", encoding="utf-8")
        mock_provider.reset_mock()
        pipeline, mock_provider = _run_pipeline(project_dir, settings)
        mock_provider.generate_with_boundaries.assert_not_called()
        assert (audio_dir / "scene-001.timing.json").exists()

        # Case 3: TTS generated + subtitle missing → both run
        (audio_dir / "scene-001.mp3").unlink()
        (audio_dir / "scene-001.timing.json").unlink()
        mock_provider.reset_mock()
        pipeline, mock_provider = _run_pipeline(project_dir, settings)
        mock_provider.generate_with_boundaries.assert_called_once()
        assert (audio_dir / "scene-001.timing.json").exists()


class TestUnconfiguredPricingWarning:
    """Bug 3: Estimated Credits/Cost show 0.0 not because of a propagation
    bug — both the per-scene log and the summary read the exact same pricing
    config — but because CARTESIA_CREDITS_PER_CHARACTER/_PER_REQUEST are
    unset (0.0) in .env. VoicePipeline now warns about this explicitly."""

    def test_warns_when_pricing_unconfigured(self):
        from ytfactory.voice.pipeline import VoicePipeline

        settings = _settings(cartesia_credits_per_character=0.0, cartesia_credits_per_request=0.0)
        with patch("ytfactory.voice.pipeline.logger") as mock_logger:
            VoicePipeline(settings)
        assert mock_logger.warning.called
        assert "not configured" in mock_logger.warning.call_args[0][0]

    def test_no_warning_when_pricing_configured(self):
        from ytfactory.voice.pipeline import VoicePipeline

        settings = _settings(cartesia_credits_per_character=0.02, cartesia_credits_per_request=0.0)
        with patch("ytfactory.voice.pipeline.logger") as mock_logger:
            VoicePipeline(settings)
        assert not mock_logger.warning.called

    def test_no_warning_when_analytics_disabled(self):
        from ytfactory.voice.pipeline import VoicePipeline

        settings = _settings(tts_analytics_enabled=False)
        with patch("ytfactory.voice.pipeline.logger") as mock_logger:
            VoicePipeline(settings)
        assert not mock_logger.warning.called
