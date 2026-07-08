"""Tests for VoicePipeline + WhisperX alignment wiring.

Verifies that when whisperx_enabled=True, forced alignment is called after
audio generation and alignment.json is written alongside the mp3.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


# ── Settings factory ──────────────────────────────────────────────────────────


def _settings(whisperx_enabled: bool = False, **overrides) -> MagicMock:
    s = MagicMock()
    s.whisperx_enabled = whisperx_enabled
    s.whisperx_device = "cpu"
    s.whisperx_model = "base"
    s.tts_auto_retry = False
    s.tts_max_retries = 1
    s.tts_validate_audio = False
    s.tts_debug = False
    s.tts_pacing_enabled = False
    s.tts_pacing_profile = "balanced"
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def project_dir(tmp_path) -> Path:
    """Minimal project directory structure."""
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
    (p / "scenes" / "scene-plan.json").write_text(
        json.dumps(scene_plan), encoding="utf-8"
    )
    return tmp_path


def _fake_generate_with_boundaries(text, output_path, **kwargs):
    """Stub provider: writes a dummy mp3 and returns empty boundaries."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"\xff\xfb" + b"\x00" * 100)
    return output_path, []


# ── Alignment wiring tests ─────────────────────────────────────────────────────


class TestAlignmentWiring:
    def _run_pipeline(self, tmp_path, settings, project_id="test-proj"):
        from ytfactory.voice.pipeline import VoicePipeline

        mock_provider = MagicMock()
        mock_provider.capabilities.provider_name = "edge"
        mock_provider.generate_with_boundaries.side_effect = _fake_generate_with_boundaries

        import os
        orig = os.getcwd()
        os.chdir(tmp_path)
        try:
            with patch("ytfactory.voice.pipeline.get_tts_provider", return_value=mock_provider), \
                 patch("ytfactory.voice.pipeline._normalize_audio_attack"), \
                 patch("ytfactory.voice.pipeline.VoiceRepository"), \
                 patch("ytfactory.voice.pipeline.TTSDebugWriter"), \
                 patch("ytfactory.voice.pipeline.SpeechOptimizer"), \
                 patch("ytfactory.voice.pipeline._optimizer") as mock_opt:
                mock_opt.optimize.return_value = "From childhood we are taught to be good."
                pipeline = VoicePipeline(settings)
                pipeline._provider = mock_provider
                pipeline.run(project_id)
        finally:
            os.chdir(orig)

    def test_alignment_not_called_when_disabled(self, project_dir):
        settings = _settings(whisperx_enabled=False)

        with patch("ytfactory.voice.pipeline.whisperx_align") as mock_align, \
             patch("ytfactory.voice.pipeline.save_alignment") as mock_save:
            self._run_pipeline(project_dir, settings)

        mock_align.assert_not_called()
        mock_save.assert_not_called()

    def test_alignment_called_when_enabled(self, project_dir):
        settings = _settings(whisperx_enabled=True)
        fake_alignment = {
            "version": "whisperx_v1",
            "words": [{"word": "From", "start": 0.1, "end": 0.3, "score": 0.99}],
            "sentences": [],
            "confidence": 0.99,
        }

        with patch("ytfactory.voice.pipeline.whisperx_align", return_value=fake_alignment) as mock_align, \
             patch("ytfactory.voice.pipeline.save_alignment") as mock_save:
            self._run_pipeline(project_dir, settings)

        mock_align.assert_called_once()
        mock_save.assert_called_once()

    def test_alignment_saved_to_correct_path(self, project_dir):
        settings = _settings(whisperx_enabled=True)
        fake_alignment = {
            "version": "whisperx_v1",
            "words": [],
            "sentences": [],
            "confidence": 0.0,
        }
        saved_paths = []

        def _capture_save(alignment, path):
            saved_paths.append(path)

        with patch("ytfactory.voice.pipeline.whisperx_align", return_value=fake_alignment), \
             patch("ytfactory.voice.pipeline.save_alignment", side_effect=_capture_save):
            self._run_pipeline(project_dir, settings)

        assert len(saved_paths) == 1
        assert saved_paths[0].name == "scene-001.alignment.json"
        assert saved_paths[0].parent.name == "audio"

    def test_alignment_skipped_if_already_exists(self, project_dir):
        settings = _settings(whisperx_enabled=True)

        # Pre-write alignment file
        audio_dir = project_dir / "workspace" / "jobs" / "test-proj" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "scene-001.alignment.json").write_text(
            '{"version":"whisperx_v1","words":[],"sentences":[],"confidence":0}',
            encoding="utf-8",
        )
        # Also pre-write audio + timing so TTS is skipped
        (audio_dir / "scene-001.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)
        (audio_dir / "scene-001.timing.json").write_text("[]", encoding="utf-8")

        with patch("ytfactory.voice.pipeline.whisperx_align") as mock_align:
            self._run_pipeline(project_dir, settings)

        mock_align.assert_not_called()

    def test_alignment_failure_does_not_abort_pipeline(self, project_dir):
        """A whisperx error is logged as a warning; the pipeline still completes."""
        settings = _settings(whisperx_enabled=True)

        with patch("ytfactory.voice.pipeline.whisperx_align", side_effect=RuntimeError("gpu oom")), \
             patch("ytfactory.voice.pipeline.save_alignment") as mock_save:
            # Should not raise
            self._run_pipeline(project_dir, settings)

        mock_save.assert_not_called()

    def test_alignment_uses_device_from_settings(self, project_dir):
        settings = _settings(whisperx_enabled=True, whisperx_device="cuda")
        fake_alignment = {"version": "whisperx_v1", "words": [], "sentences": [], "confidence": 0.0}

        with patch("ytfactory.voice.pipeline.whisperx_align", return_value=fake_alignment) as mock_align, \
             patch("ytfactory.voice.pipeline.save_alignment"):
            self._run_pipeline(project_dir, settings)

        _, kwargs = mock_align.call_args
        assert kwargs.get("device") == "cuda"

    def test_model_size_not_passed_to_align(self, project_dir):
        """model_size is no longer a parameter of align() — ensure it's not passed."""
        settings = _settings(whisperx_enabled=True)
        fake_alignment = {"version": "whisperx_v1", "words": [], "sentences": [], "confidence": 0.0}

        with patch("ytfactory.voice.pipeline.whisperx_align", return_value=fake_alignment) as mock_align, \
             patch("ytfactory.voice.pipeline.save_alignment"):
            self._run_pipeline(project_dir, settings)

        _, kwargs = mock_align.call_args
        assert "model_size" not in kwargs
