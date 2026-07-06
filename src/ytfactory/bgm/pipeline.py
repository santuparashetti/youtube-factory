"""BGMPipeline — standalone BGM orchestration (library selection + mixing).

NOTE: BGM is NOT applied via this class in the build pipeline. Background
music is mixed as a structural part of video composition inside
``VideoPipeline._compose_final_video()`` (video/pipeline.py), ensuring that
every code path producing final.mp4 — including Auto Remediation — always
outputs the fully-mixed version without any separate post-processing step.

This class exists for standalone / testing use only.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.config.settings import Settings

from .config import BGMConfig
from .detector import detect_category
from .library import BGMLibrary
from .mixer import BGMMixer
from .models import BGMMixResult

console = Console()


class BGMPipeline:
    """Background Music pipeline stage."""

    def __init__(
        self,
        config: BGMConfig | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or Settings()
        self._config = config or BGMConfig(
            enabled=self._settings.bgm_enabled,
            category=self._settings.bgm_category,
            library_path=self._settings.bgm_library_path,
            bgm_volume=self._settings.bgm_volume,
            duck_threshold=self._settings.bgm_duck_threshold,
            duck_ratio=self._settings.bgm_duck_ratio,
            duck_attack_ms=self._settings.bgm_duck_attack_ms,
            duck_release_ms=self._settings.bgm_duck_release_ms,
            fade_in_seconds=self._settings.bgm_fade_in_seconds,
            fade_out_seconds=self._settings.bgm_fade_out_seconds,
            crossfade_seconds=self._settings.bgm_crossfade_seconds,
            random_track=self._settings.bgm_random_track,
        )
        self._library = BGMLibrary(self._config)
        self._mixer = BGMMixer(self._config)

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, project_id: str, video_path: Path | None = None) -> BGMMixResult | None:
        """Mix background music into the final video for *project_id*.

        Returns the BGMMixResult when music was applied, or None when BGM is
        disabled or no suitable track was found.
        """
        if not self._config.enabled:
            return None

        project_dir = Path("workspace") / "jobs" / project_id

        if video_path is None:
            video_path = project_dir / "video" / "final.mp4"

        if not video_path.exists():
            raise FileNotFoundError(f"Final video not found: {video_path}")

        console.rule("[bold cyan]Background Music Engine[/bold cyan]")

        # ── Category selection ────────────────────────────────────────────
        category = self._resolve_category(project_dir)
        console.print(f"  [dim]Category:[/dim] [bold]{category}[/bold]")

        # ── Track selection ───────────────────────────────────────────────
        track = self._library.find_track(category)
        if track is None:
            console.print(
                f"[yellow]  ⚠ No BGM tracks found for '{category}' "
                f"in {self._config.library_path}. BGM skipped.[/yellow]"
            )
            logger.warning(
                "BGM skipped: no tracks found for category '{}' in {}",
                category,
                self._config.library_path,
            )
            return None

        console.print(f"  [dim]Track:[/dim] {track.title}")

        # ── Mix ───────────────────────────────────────────────────────────
        tmp_path = video_path.with_suffix(".bgm.mp4")
        result = self._mixer.mix(video_path, track, tmp_path)

        if result.success:
            tmp_path.replace(video_path)
            result.output_path = video_path
            size_mb = video_path.stat().st_size / 1024**2
            console.print(
                Panel(
                    f"[green]✓ BGM mixed[/green]\n"
                    f"Category: {category}\n"
                    f"Track: {track.title}\n"
                    f"Volume: {int(self._config.bgm_volume * 100)}%  "
                    f"Duck ratio: {self._config.duck_ratio:.0f}:1\n"
                    f"Output: {video_path}\n"
                    f"Size: {size_mb:.1f} MB",
                    title="Background Music Engine",
                )
            )
        else:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            console.print("[red]  ✗ BGM mixing failed — original video preserved.[/red]")
            logger.error("BGM mixing failed for project {}: {}", project_id, result.error[:300])
            raise RuntimeError(f"BGM mixing failed: {result.error[:300]}")

        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    def _resolve_category(self, project_dir: Path) -> str:
        """Return the BGM category — either explicit or auto-detected."""
        if self._config.category != "auto":
            return self._config.category

        title = self._read_project_title(project_dir)
        scene_titles = self._read_scene_titles(project_dir)
        return detect_category(title, scene_titles)

    @staticmethod
    def _read_project_title(project_dir: Path) -> str:
        try:
            data = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
            return data.get("title", project_dir.name)
        except Exception:
            return project_dir.name

    @staticmethod
    def _read_scene_titles(project_dir: Path) -> list[str]:
        try:
            data = json.loads(
                (project_dir / "scenes" / "scene-plan.json").read_text(encoding="utf-8")
            )
            return [s.get("title", "") for s in data.get("scenes", [])]
        except Exception:
            return []
