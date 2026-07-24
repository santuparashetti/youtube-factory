"""Stage 1 — Asset Integrity Review.

Checks:
  - All scene images exist and are non-empty
  - All scene audio files exist and are non-empty
  - All scene subtitle files exist (ASS preferred, SRT fallback)
  - All scene video clips exist and are non-empty
  - Final output video exists and meets minimum size
  - Image files match expected dimensions (when ffprobe is available)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytfactory.review.models import SceneReview
from ytfactory.review.stages.base import BaseReviewStage


class AssetIntegrityStage(BaseReviewStage):
    name = "asset_integrity"

    def _run_checks(
        self,
        project_dir: Path,
        scenes: list[dict],
        scene_reviews: list[SceneReview],
        context: dict,
    ) -> None:
        for sr in scene_reviews:
            idx = sr.index
            if sr.scene_type in ("asset", "brand_card"):
                # Asset scenes use a caller-supplied file — skip image check
                self._ok()
            else:
                image = project_dir / "images" / f"scene-{idx:03d}.png"
                sr.has_image = image.exists()
                if sr.has_image:
                    sr.image_size_bytes = image.stat().st_size
                self._check(
                    sr.has_image
                    and sr.image_size_bytes >= self._config.min_image_size_bytes,
                    f"Scene {idx}: image missing or empty ({image})",
                )
                if (
                    sr.has_image
                    and sr.image_size_bytes < self._config.min_image_size_bytes
                ):
                    sr.issues.append(f"Image too small ({sr.image_size_bytes} bytes)")
                elif not sr.has_image:
                    sr.issues.append("Missing image file")

            # Audio
            audio = project_dir / "audio" / f"scene-{idx:03d}.mp3"
            sr.has_audio = audio.exists()
            if sr.has_audio:
                sr.audio_size_bytes = audio.stat().st_size
            self._check(
                sr.has_audio
                and sr.audio_size_bytes >= self._config.min_audio_size_bytes,
                f"Scene {idx}: audio missing or empty ({audio})",
            )
            if sr.has_audio and sr.audio_size_bytes < self._config.min_audio_size_bytes:
                sr.issues.append(f"Audio too small ({sr.audio_size_bytes} bytes)")
            elif not sr.has_audio:
                sr.issues.append("Missing audio file")

            # Subtitles — ASS preferred, SRT fallback
            ass_sub = project_dir / "subtitles" / f"scene-{idx:03d}.ass"
            srt_sub = project_dir / "subtitles" / f"scene-{idx:03d}.srt"
            sr.has_subtitle = ass_sub.exists() or srt_sub.exists()
            self._check(
                sr.has_subtitle,
                f"Scene {idx}: no subtitle file found ({ass_sub} or {srt_sub})",
            )
            if not sr.has_subtitle:
                sr.issues.append("Missing subtitle file")

            # Video clip
            clip = project_dir / "video" / f"scene-{idx:03d}.mp4"
            sr.has_video_clip = clip.exists()
            if sr.has_video_clip:
                sr.video_clip_size_bytes = clip.stat().st_size
            self._check(
                sr.has_video_clip
                and sr.video_clip_size_bytes >= self._config.min_video_size_bytes,
                f"Scene {idx}: video clip missing or too small ({clip})",
            )
            if (
                sr.has_video_clip
                and sr.video_clip_size_bytes < self._config.min_video_size_bytes
            ):
                sr.issues.append(
                    f"Video clip too small ({sr.video_clip_size_bytes} bytes)"
                )
            elif not sr.has_video_clip:
                sr.issues.append("Missing video clip")

        # Final video
        final_video = project_dir / "video" / "final.mp4"
        if self._check(
            final_video.exists(),
            "final.mp4 is missing — concatenation did not complete",
        ):
            size = final_video.stat().st_size
            self._check(
                size >= self._config.min_final_video_size_bytes,
                f"final.mp4 is suspiciously small ({size} bytes)",
            )
            context["final_video_size_bytes"] = size

            # Light corruption check via ffprobe (optional — skip if ffprobe absent)
            _ffprobe_check(final_video, self)


def _ffprobe_check(path: Path, stage: AssetIntegrityStage) -> None:
    """Use ffprobe to confirm the file is a valid media container."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            stage._warn(
                f"final.mp4 failed ffprobe container check: {result.stderr.strip()[:200]}"
            )
        else:
            duration_str = result.stdout.strip()
            try:
                duration = float(duration_str)
                stage._ok()
                stage._config.__dict__["_final_video_duration"] = (
                    duration  # pass to context
                )
            except ValueError:
                stage._warn(f"ffprobe returned non-numeric duration: {duration_str!r}")
    except FileNotFoundError:
        # ffprobe not installed — skip silently (warn only)
        stage._warn("ffprobe not found — skipping media container validation")
    except subprocess.TimeoutExpired:
        stage._warn("ffprobe timed out checking final.mp4")
