"""Remediation executors for Auto Remediation Engine V1.

ProductionExecutor deletes specific failed artifacts, then calls the
appropriate existing pipeline to regenerate only the missing files.
The pipelines are idempotent (they skip files that already exist), so
deleting just the failed artifact is sufficient to trigger selective
re-generation.

DryRunExecutor records what would have been done without touching anything
— used in tests and when RemediationConfig.dry_run=True.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from ytfactory.review.remediation.models import RegeneratedAsset, RemediationAction


class RemediationExecutorBase:
    """Interface for remediation executors."""

    def execute(
        self,
        action: RemediationAction,
        project_dir: Path,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool = True,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        """Execute a remediation action.

        Returns:
            (success, outcome_message, list_of_regenerated_assets)
        """
        raise NotImplementedError


class ProductionExecutor(RemediationExecutorBase):
    """Execute remediations by deleting artifacts and calling existing pipelines.

    Importing pipeline dependencies here keeps the module lazy — production
    pipelines require Settings and live API keys which are absent in tests.
    """

    def execute(
        self,
        action: RemediationAction,
        project_dir: Path,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool = True,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        strategy = action.strategy
        project_id = project_dir.name

        try:
            if strategy == "regenerate_image":
                return self._regenerate_image(
                    action, project_dir, project_id, scenes, cycle, enable_rollback
                )
            elif strategy == "regenerate_audio":
                return self._regenerate_audio(
                    action, project_dir, project_id, scenes, cycle, enable_rollback
                )
            elif strategy == "regenerate_subtitles":
                return self._regenerate_subtitles(
                    action, project_dir, project_id, scenes, cycle, enable_rollback
                )
            elif strategy == "regenerate_video_clip":
                return self._regenerate_video_clip(
                    action, project_dir, project_id, scenes, cycle, enable_rollback
                )
            elif strategy == "regenerate_alignment":
                return self._regenerate_alignment(
                    action, project_dir, project_id, scenes, cycle, enable_rollback
                )
            elif strategy == "retry_validation":
                return True, "Validation retry — no artifact changes needed", []
            elif strategy == "full_regeneration":
                return self._full_regeneration(
                    action, project_dir, project_id, scenes, cycle, enable_rollback
                )
            else:
                return False, f"Unknown strategy: {strategy}", []
        except Exception as exc:
            return False, f"Executor error: {exc}", []

    # ── Strategy implementations ───────────────────────────────────────────────

    def _regenerate_image(
        self,
        action: RemediationAction,
        project_dir: Path,
        project_id: str,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        from ytfactory.config.settings import Settings
        from ytfactory.images.pipeline import ImagePipeline

        targets = _scene_files(project_dir / "images", action.scene_index, "*.png")
        assets = _backup_and_delete(
            targets,
            project_dir,
            cycle,
            action.strategy,
            "image",
            action.scene_index,
            enable_rollback,
        )
        ImagePipeline(Settings()).run(project_id)
        return True, f"Regenerated {len(targets)} image(s)", assets

    def _regenerate_audio(
        self,
        action: RemediationAction,
        project_dir: Path,
        project_id: str,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        from ytfactory.config.settings import Settings
        from ytfactory.voice.pipeline import VoicePipeline

        audio_dir = project_dir / "audio"
        mp3_files = _scene_files(audio_dir, action.scene_index, "*.mp3")
        timing_files = _scene_files(audio_dir, action.scene_index, "*.timing.json")
        targets = mp3_files + timing_files
        assets = _backup_and_delete(
            targets,
            project_dir,
            cycle,
            action.strategy,
            "audio",
            action.scene_index,
            enable_rollback,
        )
        VoicePipeline(Settings()).run(project_id)
        return True, f"Regenerated {len(mp3_files)} audio file(s)", assets

    def _regenerate_subtitles(
        self,
        action: RemediationAction,
        project_dir: Path,
        project_id: str,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        from ytfactory.captions.pipeline import CaptionPipeline

        sub_dir = project_dir / "subtitles"
        srt_files = _scene_files(sub_dir, action.scene_index, "*.srt")
        ass_files = _scene_files(sub_dir, action.scene_index, "*.ass")
        targets = srt_files + ass_files
        assets = _backup_and_delete(
            targets,
            project_dir,
            cycle,
            action.strategy,
            "subtitle",
            action.scene_index,
            enable_rollback,
        )
        CaptionPipeline().run(project_id)
        return True, f"Regenerated {len(srt_files)} subtitle file(s)", assets

    def _regenerate_video_clip(
        self,
        action: RemediationAction,
        project_dir: Path,
        project_id: str,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        from ytfactory.video.pipeline import VideoPipeline

        video_dir = project_dir / "video"
        targets = _scene_files(video_dir, action.scene_index, "*.mp4")
        # Also delete final.mp4 so it gets rebuilt
        final = video_dir / "final.mp4"
        if final.exists():
            targets.append(final)
        assets = _backup_and_delete(
            targets,
            project_dir,
            cycle,
            action.strategy,
            "rendering",
            action.scene_index,
            enable_rollback,
        )
        VideoPipeline().run(project_id)
        return True, f"Re-rendered {len(targets)} video file(s)", assets

    def _regenerate_alignment(
        self,
        action: RemediationAction,
        project_dir: Path,
        project_id: str,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        """Delete alignment files and re-run VoicePipeline to regenerate them.

        Audio (mp3) is preserved; VoicePipeline skips existing audio and only
        re-runs WhisperX alignment when WHISPERX_ENABLED=true.
        """
        from ytfactory.config.settings import Settings

        audio_dir = project_dir / "audio"
        alignment_files = _scene_files(
            audio_dir, action.scene_index, "*.alignment.json"
        )
        assets = _backup_and_delete(
            alignment_files,
            project_dir,
            cycle,
            action.strategy,
            "subtitle",
            action.scene_index,
            enable_rollback,
        )
        settings = Settings()
        if settings.whisperx_enabled:
            from ytfactory.voice.pipeline import VoicePipeline

            VoicePipeline(settings).run(project_id)
        return True, f"Regenerated {len(alignment_files)} alignment file(s)", assets

    def _full_regeneration(
        self,
        action: RemediationAction,
        project_dir: Path,
        project_id: str,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        from ytfactory.config.settings import Settings
        from ytfactory.captions.pipeline import CaptionPipeline
        from ytfactory.images.pipeline import ImagePipeline
        from ytfactory.video.pipeline import VideoPipeline
        from ytfactory.voice.pipeline import VoicePipeline

        all_targets: list[Path] = []
        for subdir, pattern in [
            ("images", "*.png"),
            ("audio", "*.mp3"),
            ("audio", "*.timing.json"),
            ("audio", "*.alignment.json"),
            ("subtitles", "*.srt"),
            ("subtitles", "*.ass"),
            ("video", "*.mp4"),
        ]:
            all_targets.extend(_scene_files(project_dir / subdir, None, pattern))

        assets = _backup_and_delete(
            all_targets,
            project_dir,
            cycle,
            action.strategy,
            action.category,
            None,
            enable_rollback,
        )
        settings = Settings()
        ImagePipeline(settings).run(project_id)
        VoicePipeline(settings).run(project_id)
        CaptionPipeline().run(project_id)
        VideoPipeline().run(project_id)
        return True, f"Full regeneration: {len(all_targets)} files rebuilt", assets


class DryRunExecutor(RemediationExecutorBase):
    """Record what would be done without touching the filesystem."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(
        self,
        action: RemediationAction,
        project_dir: Path,
        scenes: list[dict],
        cycle: int,
        enable_rollback: bool = True,
    ) -> tuple[bool, str, list[RegeneratedAsset]]:
        self.calls.append(
            {
                "action_id": action.action_id,
                "strategy": action.strategy,
                "engine_target": action.engine_target,
                "category": action.category,
                "scene_index": action.scene_index,
                "cycle": cycle,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        return True, f"[dry-run] Would execute: {action.strategy}", []


# ── Helpers ───────────────────────────────────────────────────────────────────


def _scene_files(directory: Path, scene_index: int | None, pattern: str) -> list[Path]:
    """Return matching files in `directory`.

    If scene_index is given, only files whose name starts with
    'scene-<NNN>' are returned (targeted remediation).
    Otherwise, all matching files are returned.
    """
    if not directory.exists():
        return []
    all_files = list(directory.glob(pattern))
    if scene_index is None:
        return all_files
    prefix = f"scene-{scene_index:03d}"
    return [f for f in all_files if f.name.startswith(prefix)]


def _backup_and_delete(
    files: list[Path],
    project_dir: Path,
    cycle: int,
    strategy: str,
    category: str,
    scene_index: int | None,
    enable_rollback: bool,
) -> list[RegeneratedAsset]:
    """Back up and delete files, return regenerated-asset records."""
    backup_dir = project_dir / "remediation" / "backups" / f"cycle-{cycle:02d}"
    assets: list[RegeneratedAsset] = []

    for fp in files:
        if not fp.exists():
            continue
        backed_up_to = ""
        if enable_rollback:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / fp.name
            shutil.copy2(fp, backup_path)
            backed_up_to = str(backup_path)
        fp.unlink()
        assets.append(
            RegeneratedAsset(
                cycle=cycle,
                strategy=strategy,
                category=category,
                scene_index=scene_index,
                file_path=str(fp),
                backed_up_to=backed_up_to,
            )
        )
    return assets
