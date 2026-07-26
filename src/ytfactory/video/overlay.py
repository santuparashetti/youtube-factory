from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_RAIN_MOODS = {"grief", "penance", "longing"}
_MOTION_ALIASES = {
    "fog": "smoke",
    "dust": "smoke",
}

# Task 2.9 — grain fires only when the video's overall composition warrants
# a film-grain texture; era/mood/visual_style come from each scene's
# visual_metadata (VisualMetadata: era, mood, visual_style), not flat fields.
_GRAIN_ERAS = {"HISTORICAL", "ANCIENT", "SYMBOLIC", "TRANSITIONAL"}
_GRAIN_MOODS = {"reverent", "mysterious", "reflective", "fearful", "lonely"}
_GRAIN_STYLES = {"CINEMATIC", "DOCUMENTARY"}


class OverlayCompositor:
    """Second-pass overlay compositing.

    Reads motion_type from each scene dict and overlays corresponding
    category clips from the manifest. Overlays are applied only when
    the scene maps to a category; no overlay is forced.
    """

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        skip: bool = False,
        assets_dir: str | Path = "assets/overlays",
    ) -> None:
        self.skip = skip
        self.manifest: dict = {}
        self.manifest_path = Path(manifest_path) if manifest_path else None
        self.assets_dir = Path(assets_dir)
        if not self.skip and self.manifest_path:
            self._load_manifest()

    def _load_manifest(self) -> None:
        path = self.manifest_path
        if not path or not path.is_absolute():
            path = Path(os.getcwd()) / self.manifest_path if self.manifest_path else None
        if path and path.is_file():
            try:
                with path.open("r", encoding="utf-8") as f:
                    self.manifest = json.load(f)
                logger.info("Loaded overlay manifest: %s", path)
            except Exception as exc:
                logger.warning("Failed to load overlay manifest %s: %s", path, exc)
                self.manifest = {}
        else:
            logger.info("Overlay manifest not found at %s — overlay compositing disabled", path)

    def _resolve_motion_type(self, scene: dict) -> str | None:
        motion_type = scene.get("motion_type")
        if not motion_type:
            motion = scene.get("motion") or {}
            motion_type = motion.get("motion_type") if isinstance(motion, dict) else None
        if motion_type:
            return str(motion_type).lower().strip()
        return None

    def _resolve_mood(self, scene: dict) -> str | None:
        visual_metadata = scene.get("visual_metadata")
        if visual_metadata is None:
            return None
        if hasattr(visual_metadata, "mood"):
            mood = visual_metadata.mood
            if mood and hasattr(mood, "value"):
                return str(mood.value).lower().strip()
            return str(mood).lower().strip() if mood else None
        if isinstance(visual_metadata, dict):
            mood = visual_metadata.get("mood")
            if mood:
                if hasattr(mood, "value"):
                    return str(mood.value).lower().strip()
                return str(mood).lower().strip()
        return None

    @staticmethod
    def _visual_metadata_field(scene: dict, field_name: str) -> str:
        """Read a field (era/mood/visual_style) off scene.visual_metadata,
        handling both a VisualMetadata object and its dict/JSON form. Returns
        "" when absent — grain checks treat that as non-matching, not an error.
        """
        visual_metadata = scene.get("visual_metadata")
        if visual_metadata is None:
            return ""
        value = (
            getattr(visual_metadata, field_name, None)
            if not isinstance(visual_metadata, dict)
            else visual_metadata.get(field_name)
        )
        if value is None:
            return ""
        if hasattr(value, "value"):
            value = value.value
        return str(value).strip()

    def _should_apply_grain(self, scenes: list[dict]) -> bool:
        """True if ANY scene's visual_metadata (era/mood/visual_style)
        warrants film grain. Task 2.9 — grain is conditional on overall
        composition, not applied to every video unconditionally."""
        for scene in scenes:
            if scene.get("scene_type") == "brand_card":
                continue

            era = self._visual_metadata_field(scene, "era").upper()
            mood = self._visual_metadata_field(scene, "mood").lower()
            style = self._visual_metadata_field(scene, "visual_style").upper()

            if era in _GRAIN_ERAS:
                return True
            if mood in _GRAIN_MOODS:
                return True
            if style in _GRAIN_STYLES:
                return True

        return False

    def select_category(self, scene: dict) -> tuple[str | None, str | None]:
        """Return (category, motion_type) for the scene's mood overlay.

        None means no overlay applies for this scene.
        """
        motion_type = self._resolve_motion_type(scene)
        if not motion_type:
            return None, None
        if not self.manifest:
            return None, None

        mapped = _MOTION_ALIASES.get(motion_type, motion_type)
        if mapped in self.manifest:
            clip_list = self.manifest[mapped]
            if clip_list:
                return mapped, motion_type

        mood = self._resolve_mood(scene)
        if mood in _RAIN_MOODS and "rain" in self.manifest:
            return "rain", motion_type if motion_type == "rain" else f"mood:{mood}"

        return None, motion_type

    def compositing_passes_needed(self, scene: dict) -> int:
        """Return 1 if a category matches, 0 otherwise."""
        if self.skip:
            return 0
        category, _ = self.select_category(scene)
        return 1 if category else 0

    def run_overlay_pass(
        self,
        scene_input: Path,
        scene_output: Path,
        duration_hint: float,
        category: str,
        scene_index: int,
        width: int,
        height: int,
        fps: int = 30,
    ) -> tuple[Path, float]:
        """Run a single overlay compositing ffmpeg pass.

        Returns (output_path, elapsed_seconds).
        """
        clips = self.manifest.get(category, [])
        if not clips:
            raise ValueError(f"No clips found for overlay category: {category}")

        clip = clips[scene_index % len(clips)]
        blend_mode = clip.get("blend_mode", "screen")
        opacity = float(clip.get("opacity", 0.25))
        overlay_rel = clip["file"]

        overlay_base = self.assets_dir if self.assets_dir.is_absolute() else Path(os.getcwd()) / self.assets_dir
        overlay_path = overlay_base / overlay_rel
        if not overlay_path.is_file():
            raise FileNotFoundError(f"Overlay clip not found: {overlay_path}")

        fps = max(1, int(fps))
        dur = max(0.1, float(duration_hint))

        args = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(scene_input),
        ]

        filter_complex = (
            f"[1:v]scale={width}:{height},setsar=1,format=rgba,"
            f"colorchannelmixer=aa={opacity:.2f},trim=duration={dur:.4f}[ov]; "
            f"[0:v][ov]blend=all_mode={blend_mode}:shortest=1[outv]"
        )

        args += [
            "-stream_loop",
            "-1",
            "-i",
            str(overlay_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-map",
            "0:a?",
            "-c:a",
            "copy",
            "-shortest",
            "-s",
            f"{width}x{height}",
            "-r",
            str(fps),
            str(scene_output),
        ]

        t0 = time.perf_counter()
        subprocess.run(args, check=True, capture_output=True)
        elapsed = time.perf_counter() - t0

        logger.info(
            "Scene %d overlay compositing: category=%s clip=%s opacity=%.2f mode=%s elapsed=%.2fs",
            scene_index,
            category,
            overlay_rel,
            opacity,
            blend_mode,
            elapsed,
        )
        return scene_output, elapsed

    def apply_overlays_to_scene(
        self,
        scene_mp4: Path,
        scene_index: int,
        scene: dict,
        duration_hint: float,
        width: int,
        height: int,
        fps: int = 30,
    ) -> tuple[Path, float]:
        """Apply overlays using scene metadata for category lookup.

        Returns (final_output_path, total_elapsed_seconds).
        """
        if self.skip or not self.manifest or not scene_mp4.is_file():
            return scene_mp4, 0.0

        total_elapsed = 0.0
        current = scene_mp4
        pass_label = f"scene-{scene_index:03d}-overlay"

        category, motion_type = self.select_category(scene)
        logger.info(
            "Scene %d overlay lookup: motion_type=%s mapped_category=%s",
            scene_index,
            motion_type,
            category,
        )

        if not category:
            return scene_mp4, 0.0

        tmp_p1 = scene_mp4.parent / f"{pass_label}-mood.tmp.mp4"
        _, elapsed = self.run_overlay_pass(
            category=category,
            scene_input=current,
            scene_output=tmp_p1,
            duration_hint=duration_hint,
            scene_index=scene_index,
            width=width,
            height=height,
            fps=fps,
        )
        total_elapsed += elapsed
        if current != scene_mp4:
            current.unlink(missing_ok=True)
        current = tmp_p1

        final = scene_mp4.parent / f"scene-{scene_index:03d}.mp4"
        current.replace(final)
        return final, total_elapsed
