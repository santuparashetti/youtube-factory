"""Tests for the regenerate_alignment remediation strategy.

Covers:
  - ProductionExecutor dispatches to _regenerate_alignment for strategy="regenerate_alignment"
  - Alignment files are deleted (with backup when enable_rollback=True)
  - VoicePipeline is called only when whisperx_enabled=True
  - DryRunExecutor records regenerate_alignment without touching the filesystem
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.review.remediation.executor import DryRunExecutor, ProductionExecutor
from ytfactory.review.remediation.models import RemediationAction


# ── Helpers ───────────────────────────────────────────────────────────────────


def _action(scene_index: int | None = 1) -> RemediationAction:
    return RemediationAction(
        action_id="ARE-0001",
        strategy="regenerate_alignment",
        engine_target="ASS Subtitle Engine",
        category="subtitle",
        severity="medium",
        confidence=80,
        rationale="Subtitle timing will improve with fresh alignment data.",
        scene_index=scene_index,
    )


def _make_project(tmp_path: Path, scene_index: int = 1) -> Path:
    """Create a minimal project directory with alignment files."""
    project_dir = tmp_path / "test-proj"
    audio_dir = project_dir / "audio"
    audio_dir.mkdir(parents=True)

    # Write alignment + audio files for the scene
    (audio_dir / f"scene-{scene_index:03d}.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)
    (audio_dir / f"scene-{scene_index:03d}.alignment.json").write_text(
        '{"version":"whisperx_v1","words":[],"sentences":[],"confidence":0}',
        encoding="utf-8",
    )
    return project_dir


# ── ProductionExecutor — regenerate_alignment ─────────────────────────────────


class TestProductionExecutorRegenerateAlignment:
    def _mock_settings(self, whisperx_enabled: bool = True) -> MagicMock:
        s = MagicMock()
        s.whisperx_enabled = whisperx_enabled
        return s

    def test_deletes_alignment_file(self, tmp_path):
        project_dir = _make_project(tmp_path)
        alignment_file = project_dir / "audio" / "scene-001.alignment.json"
        assert alignment_file.exists()

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings()), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            mock_vp_cls.return_value.run = MagicMock()
            success, msg, assets = executor.execute(
                _action(), project_dir, [], cycle=1, enable_rollback=False
            )

        assert not alignment_file.exists()
        assert success is True

    def test_calls_voice_pipeline_when_whisperx_enabled(self, tmp_path):
        project_dir = _make_project(tmp_path)
        mock_vp = MagicMock()

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings(True)), \
             patch("ytfactory.voice.pipeline.VoicePipeline", return_value=mock_vp):
            executor.execute(_action(), project_dir, [], cycle=1, enable_rollback=False)

        mock_vp.run.assert_called_once_with(project_dir.name)

    def test_skips_voice_pipeline_when_whisperx_disabled(self, tmp_path):
        project_dir = _make_project(tmp_path)

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings(False)), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            executor.execute(_action(), project_dir, [], cycle=1, enable_rollback=False)

        mock_vp_cls.assert_not_called()

    def test_preserves_mp3_files(self, tmp_path):
        """Alignment regeneration must NOT delete audio (mp3) files."""
        project_dir = _make_project(tmp_path)
        mp3 = project_dir / "audio" / "scene-001.mp3"
        assert mp3.exists()

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings()), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            mock_vp_cls.return_value.run = MagicMock()
            executor.execute(_action(), project_dir, [], cycle=1, enable_rollback=False)

        assert mp3.exists()

    def test_creates_backup_when_rollback_enabled(self, tmp_path):
        project_dir = _make_project(tmp_path)

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings()), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            mock_vp_cls.return_value.run = MagicMock()
            success, msg, assets = executor.execute(
                _action(), project_dir, [], cycle=1, enable_rollback=True
            )

        assert len(assets) == 1
        assert assets[0].backed_up_to != ""
        backup = Path(assets[0].backed_up_to)
        assert backup.exists()

    def test_returns_asset_record_for_deleted_file(self, tmp_path):
        project_dir = _make_project(tmp_path)

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings()), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            mock_vp_cls.return_value.run = MagicMock()
            success, msg, assets = executor.execute(
                _action(), project_dir, [], cycle=1, enable_rollback=False
            )

        assert success is True
        assert len(assets) == 1
        assert "alignment.json" in assets[0].file_path

    def test_outcome_message_mentions_count(self, tmp_path):
        project_dir = _make_project(tmp_path)

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings()), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            mock_vp_cls.return_value.run = MagicMock()
            _, msg, _ = executor.execute(
                _action(), project_dir, [], cycle=1, enable_rollback=False
            )

        assert "1" in msg

    def test_no_files_when_alignment_already_absent(self, tmp_path):
        """If alignment files don't exist, succeed with 0 assets deleted."""
        project_dir = _make_project(tmp_path)
        (project_dir / "audio" / "scene-001.alignment.json").unlink()

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings()), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            mock_vp_cls.return_value.run = MagicMock()
            success, msg, assets = executor.execute(
                _action(), project_dir, [], cycle=1, enable_rollback=False
            )

        assert success is True
        assert assets == []

    def test_targeted_by_scene_index(self, tmp_path):
        """With scene_index=1, only scene-001.alignment.json is deleted."""
        project_dir = _make_project(tmp_path, scene_index=1)
        audio_dir = project_dir / "audio"

        # Add a second scene's alignment file
        (audio_dir / "scene-002.alignment.json").write_text(
            '{"version":"whisperx_v1","words":[],"sentences":[],"confidence":0}',
            encoding="utf-8",
        )

        executor = ProductionExecutor()
        with patch("ytfactory.config.settings.Settings", return_value=self._mock_settings()), \
             patch("ytfactory.voice.pipeline.VoicePipeline") as mock_vp_cls:
            mock_vp_cls.return_value.run = MagicMock()
            executor.execute(_action(scene_index=1), project_dir, [], cycle=1, enable_rollback=False)

        assert not (audio_dir / "scene-001.alignment.json").exists()
        assert (audio_dir / "scene-002.alignment.json").exists()


# ── DryRunExecutor ────────────────────────────────────────────────────────────


class TestDryRunExecutorRegenerateAlignment:
    def test_records_call_without_touching_files(self, tmp_path):
        project_dir = _make_project(tmp_path)
        alignment_file = project_dir / "audio" / "scene-001.alignment.json"

        executor = DryRunExecutor()
        success, msg, assets = executor.execute(
            _action(), project_dir, [], cycle=1
        )

        assert success is True
        assert "[dry-run]" in msg
        assert alignment_file.exists()  # file untouched

    def test_records_strategy_in_calls_log(self, tmp_path):
        project_dir = _make_project(tmp_path)
        executor = DryRunExecutor()
        executor.execute(_action(), project_dir, [], cycle=2)

        assert len(executor.calls) == 1
        assert executor.calls[0]["strategy"] == "regenerate_alignment"
        assert executor.calls[0]["cycle"] == 2
