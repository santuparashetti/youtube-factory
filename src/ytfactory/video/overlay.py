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

# Task 2.11 Fix 1 — secondary visual_prompt keyword trigger, scoped to these
# four categories only. God rays and everything else stay motion_type/mood-only.
# Priority when multiple match: particles > smoke > fog > rain.
_VISUAL_KEYWORDS: dict[str, set[str]] = {
    "rain": {
        "rain", "downpour", "monsoon", "rainfall", "rainstorm",
        "drizzle", "shower", "precipitation", "pouring",
    },
    "particles": {
        "particles", "dust motes", "floating dust", "pollen",
        "embers", "sparks", "fireflies", "motes", "spores",
        "drifting particles", "swirling dust",
    },
    "smoke": {
        "smoke", "incense", "steam", "smoke rising", "smoky",
        "vapour", "vapor",
    },
    "fog": {
        "mist", "fog", "haze", "misty", "foggy", "low cloud",
        "morning mist", "evening mist",
    },
}

# Task 2.11 Fix 2 — overlays must enhance atmosphere subtly, never darken or
# overpower the base video. Keyed by manifest category name (post-alias).
OVERLAY_MAX_OPACITIES: dict[str, float] = {
    "grain": 0.03,
    "rain": 0.12,
    "particles": 0.10,
    "smoke": 0.10,
    "god_rays": 0.12,
}


def resolve_blend_and_opacity(category: str, clip: dict) -> tuple[str, float]:
    """Single source of truth for a manifest clip's blend mode + opacity.

    Screen for every mood category (never darkens), overlay for grain
    (grainmerge darkens mid-tones); opacity clamped to the category's max
    regardless of what the manifest clip itself specifies. Shared by
    run_overlay_pass() and pipeline._apply_overlays() so the two overlay
    render paths can't drift apart.
    """
    blend_mode = "overlay" if category == "grain" else "screen"
    max_opacity = OVERLAY_MAX_OPACITIES.get(category, 0.12)
    opacity = min(float(clip.get("opacity", max_opacity)), max_opacity)
    return blend_mode, opacity


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
        """True when at least 40% of content scenes' visual_metadata
        (era/mood/visual_style) warrant film grain.

        Task 2.11 Fix 3 — was "any scene matches", which fired grain on
        almost every video since a single historical/reverent scene sufficed.
        A minority-share threshold means grain now reflects the video's
        overall composition, not one outlier scene."""
        content_scenes = [s for s in scenes if s.get("scene_type") != "brand_card"]
        if not content_scenes:
            return False

        matching = 0
        for scene in content_scenes:
            era = self._visual_metadata_field(scene, "era").upper()
            mood = self._visual_metadata_field(scene, "mood").lower()
            style = self._visual_metadata_field(scene, "visual_style").upper()

            if era in _GRAIN_ERAS or mood in _GRAIN_MOODS or style in _GRAIN_STYLES:
                matching += 1

        threshold = 0.40
        ratio = matching / len(content_scenes)
        result = ratio >= threshold
        logger.debug(
            "Grain check: %d/%d scenes (%.0f%%) — threshold=%.0f%% — %s",
            matching,
            len(content_scenes),
            ratio * 100,
            threshold * 100,
            "ON" if result else "OFF",
        )
        return result

    def _category_from_visual_prompt(self, visual_prompt: str) -> str | None:
        """Secondary visual-prompt keyword check — ONLY rain/particles/smoke/fog.

        Returns the raw (pre-alias) keyword category, or None if nothing
        matches. ``select_category`` maps the result through
        ``_MOTION_ALIASES`` before checking it against the manifest, same as
        it already does for motion_type. Priority: particles > smoke > fog > rain.
        """
        prompt_lower = (visual_prompt or "").lower()
        for category in ("particles", "smoke", "fog", "rain"):
            if any(kw in prompt_lower for kw in _VISUAL_KEYWORDS[category]):
                return category
        return None

    def select_category(self, scene: dict) -> tuple[str | None, str | None]:
        """Return (category, motion_type) for the scene's mood overlay.

        None means no overlay applies for this scene.
        """
        if not self.manifest:
            return None, None

        motion_type = self._resolve_motion_type(scene)

        if motion_type:
            mapped = _MOTION_ALIASES.get(motion_type, motion_type)
            if mapped in self.manifest:
                clip_list = self.manifest[mapped]
                if clip_list:
                    return mapped, motion_type

            mood = self._resolve_mood(scene)
            if mood in _RAIN_MOODS and "rain" in self.manifest:
                return "rain", motion_type if motion_type == "rain" else f"mood:{mood}"

        # Secondary: visual_prompt keyword check — rain/particles/smoke/fog
        # only (Task 2.11 Fix 1). Primary motion_type/mood match above always
        # wins when present; this only fires as a fallback.
        keyword_category = self._category_from_visual_prompt(scene.get("visual_prompt", ""))
        if keyword_category:
            mapped = _MOTION_ALIASES.get(keyword_category, keyword_category)
            clip_list = self.manifest.get(mapped)
            if clip_list:
                return mapped, motion_type or f"visual:{keyword_category}"

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
        blend_mode, opacity = resolve_blend_and_opacity(category, clip)
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

        # Both blend inputs must share a pixel format — feeding blend a
        # yuv420p base against an rgba overlay (base left unformatted) is
        # what produces a magenta/pink cast, since FFmpeg's blend filter
        # doesn't validate/convert mismatched formats between its inputs.
        # Convert back to yuv420p after blending — libx264 can't encode rgba.
        filter_complex = (
            f"[0:v]format=rgba[base]; "
            f"[1:v]scale={width}:{height},setsar=1,format=rgba,"
            f"colorchannelmixer=aa={opacity:.2f},trim=duration={dur:.4f}[ov]; "
            f"[base][ov]blend=all_mode={blend_mode}:shortest=1,format=yuv420p[outv]"
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
