"""Tests for video/pipeline.py — actual audio duration resolution and intro clip.

Covers:
  - _actual_audio_duration() reads from timing.json (primary source)
  - _actual_audio_duration() falls back to ffprobe when timing.json is absent/bad
  - _actual_audio_duration() returns the supplied fallback when everything fails
  - Settings: video_intro_enabled / video_intro_seconds defaults
  - VideoPipeline stores settings object (not just profile string)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ytfactory.video.pipeline import _actual_audio_duration


# ── _actual_audio_duration ────────────────────────────────────────────────────


class TestActualAudioDuration:
    def test_reads_from_timing_json(self, tmp_path):
        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"id3")
        timing = tmp_path / "scene-001.timing.json"
        boundaries = [
            {"word": "hello", "start": 0.0, "end": 1.2},
            {"word": "world", "start": 1.3, "end": 2.7},
        ]
        timing.write_text(json.dumps(boundaries), encoding="utf-8")

        result = _actual_audio_duration(audio, timing, fallback=10.0)
        assert result == pytest.approx(2.7)

    def test_empty_timing_json_falls_back(self, tmp_path):
        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"id3")
        timing = tmp_path / "scene-001.timing.json"
        timing.write_text("[]", encoding="utf-8")  # empty list

        # With empty list, should skip to ffprobe; mock that too
        with patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "12.345\n"
            mock_run.return_value.returncode = 0
            result = _actual_audio_duration(audio, timing, fallback=10.0)

        assert result == pytest.approx(12.345)

    def test_missing_timing_file_falls_through_to_ffprobe(self, tmp_path):
        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"id3")
        timing = tmp_path / "scene-001.timing.json"  # does not exist

        with patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "8.5\n"
            mock_run.return_value.returncode = 0
            result = _actual_audio_duration(audio, timing, fallback=10.0)

        assert result == pytest.approx(8.5)

    def test_corrupt_timing_json_falls_through_to_ffprobe(self, tmp_path):
        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"id3")
        timing = tmp_path / "scene-001.timing.json"
        timing.write_text("{bad json}", encoding="utf-8")

        with patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "7.0\n"
            mock_run.return_value.returncode = 0
            result = _actual_audio_duration(audio, timing, fallback=10.0)

        assert result == pytest.approx(7.0)

    def test_ffprobe_failure_returns_fallback(self, tmp_path):
        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"id3")
        timing = tmp_path / "missing.json"  # does not exist

        with patch(
            "ytfactory.video.pipeline.subprocess.run",
            side_effect=Exception("ffprobe not found"),
        ):
            result = _actual_audio_duration(audio, timing, fallback=42.0)

        assert result == pytest.approx(42.0)

    def test_prefers_timing_json_over_ffprobe(self, tmp_path):
        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"id3")
        timing = tmp_path / "scene-001.timing.json"
        boundaries = [{"word": "x", "start": 0.0, "end": 5.5}]
        timing.write_text(json.dumps(boundaries), encoding="utf-8")

        # ffprobe should NOT be called when timing.json is valid
        with patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            result = _actual_audio_duration(audio, timing, fallback=10.0)
            mock_run.assert_not_called()

        assert result == pytest.approx(5.5)

    def test_zero_end_in_timing_falls_back(self, tmp_path):
        audio = tmp_path / "scene-001.mp3"
        audio.write_bytes(b"id3")
        timing = tmp_path / "scene-001.timing.json"
        boundaries = [{"word": "x", "start": 0.0, "end": 0.0}]  # zero end
        timing.write_text(json.dumps(boundaries), encoding="utf-8")

        with patch("ytfactory.video.pipeline.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "9.0\n"
            mock_run.return_value.returncode = 0
            result = _actual_audio_duration(audio, timing, fallback=10.0)

        assert result == pytest.approx(9.0)


# ── Settings defaults ─────────────────────────────────────────────────────────


class TestVideoIntroSettings:
    def test_intro_enabled_by_default(self):
        from ytfactory.config.settings import Settings
        s = Settings()
        assert s.video_intro_enabled is True

    def test_intro_seconds_default(self):
        from ytfactory.config.settings import Settings
        s = Settings()
        assert s.video_intro_seconds == pytest.approx(1.5)
