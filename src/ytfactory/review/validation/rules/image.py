"""Image validation rules (category D).

Rules:
  IMG_001 [critical] — Image file exists for every generated scene
  IMG_002 [high]     — Image file meets minimum size
  IMG_003 [high]     — Visual prompt is present for every generated scene
  IMG_004 [medium]   — No repeated visual prompts (Jaccard similarity)
  IMG_005 [low]      — Shot type assigned (V4 shot-type coverage)
  IMG_006 [medium]   — Visual prompt contains at least one style marker
  IMG_007 [medium]   — Static-hold cap: asset is still image and narration > 8 s
  IMG_008 [medium]   — Brightness floor for warmth/intimacy scenes
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult

# Moods whose scenes are expected to carry warmth, light, or human presence.
# Somber-tagged scenes (FEARFUL, LONELY, MYSTERIOUS) are intentionally exempt
# from the brightness floor so grief/darkness can be expressed visually.
_WARMTH_INTIMACY_MOODS = frozenset({
    "PEACEFUL",
    "HOPEFUL",
    "REVERENT",
    "REFLECTIVE",
    "DETERMINED",
})


def _jaccard(a: str, b: str) -> float:
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _avg_luminance(img_path: Path) -> float | None:
    """Return average 0-255 luminance for an image, or None on failure."""
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return None
    try:
        with Image.open(img_path) as img:
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            return float(stat.mean[0])
    except Exception:
        return None


class ImageValidator(BaseValidator):
    category = "image"
    responsible_engine = "ImageGenerator"

    def validate(
        self,
        project_dir: Path,
        scenes: list[dict],
        context: dict,
    ) -> list[ValidationResult]:
        results: list[ValidationResult] = []

        generated = [
            s
            for s in scenes
            if s.get("scene_type", "generated_image") == "generated_image"
        ]

        if not scenes:
            for rule_id in (
                "IMG_001",
                "IMG_002",
                "IMG_003",
                "IMG_004",
                "IMG_005",
                "IMG_006",
                "IMG_007",
                "IMG_008",
            ):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        prompts: list[tuple[int, str]] = []  # (index, visual_prompt)

        for scene in generated:
            idx = scene.get("index", 0)
            img_path = project_dir / "images" / f"scene-{idx:03d}.png"
            dur = float(scene.get("duration_seconds", 0.0))
            visual_prompt = scene.get("visual_prompt", "")

            # IMG_001: Image exists
            if self._config.is_enabled("IMG_001"):
                if not img_path.exists():
                    results.append(
                        self._fail(
                            "IMG_001",
                            f"Scene {idx}: image file missing",
                            f"Expected: {img_path.name}",
                            "critical",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "IMG_001",
                            f"Scene {idx} image exists",
                            img_path.name,
                            scene_index=idx,
                        )
                    )

            # IMG_002: Image minimum size
            if self._config.is_enabled("IMG_002") and img_path.exists():
                size = img_path.stat().st_size
                min_size = self._config.image_min_size_bytes
                if size < min_size:
                    results.append(
                        self._fail(
                            "IMG_002",
                            f"Scene {idx}: image file too small ({size} bytes)",
                            f"size_bytes={size}, min={min_size}",
                            "high",
                            scene_index=idx,
                            size_bytes=size,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "IMG_002",
                            f"Scene {idx} image size OK",
                            f"{size} bytes",
                            scene_index=idx,
                        )
                    )

            # IMG_003: Visual prompt present
            if self._config.is_enabled("IMG_003"):
                if not visual_prompt or not visual_prompt.strip():
                    results.append(
                        self._fail(
                            "IMG_003",
                            f"Scene {idx}: visual prompt missing",
                            f"scene_index={idx}, visual_prompt=empty",
                            "high",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "IMG_003",
                            f"Scene {idx} has visual prompt",
                            f"{len(visual_prompt.split())} words",
                            scene_index=idx,
                        )
                    )

            if visual_prompt.strip():
                prompts.append((idx, visual_prompt))

            # IMG_005: Shot type assigned
            if self._config.is_enabled("IMG_005"):
                shot_type = scene.get("shot_type", "")
                if not shot_type:
                    results.append(
                        self._warn(
                            "IMG_005",
                            f"Scene {idx}: no shot type assigned",
                            f"scene_index={idx}",
                            "low",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "IMG_005",
                            f"Scene {idx} has shot type",
                            shot_type,
                            scene_index=idx,
                        )
                    )

            # IMG_006: Style markers in visual prompt
            if self._config.is_enabled("IMG_006") and visual_prompt.strip():
                markers = self._config.image_style_markers
                lower_p = visual_prompt.lower()
                found = [m for m in markers if m.lower() in lower_p]
                if not found:
                    results.append(
                        self._warn(
                            "IMG_006",
                            f"Scene {idx}: visual prompt lacks style markers",
                            f"prompt excerpt: '{visual_prompt[:60]}'",
                            "medium",
                            scene_index=idx,
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "IMG_006",
                            f"Scene {idx} has style markers",
                            f"found: {found[:3]}",
                            scene_index=idx,
                        )
                    )

            # IMG_007: Static-hold duration cap
            if self._config.is_enabled("IMG_007") and img_path.exists():
                threshold = self._config.image_static_hold_max_seconds
                motion_type = scene.get("motion", {}).get("motion_type", "static")
                if motion_type != "static":
                    results.append(
                        self._skip(
                            "IMG_007",
                            f"scene_index={idx}, motion_type={motion_type} "
                            f"(non-static motion — not a static hold)",
                            scene_index=idx,
                        )
                    )
                elif dur > threshold:
                    results.append(
                        self._warn(
                            "IMG_007",
                            f"Scene {idx}: static-hold duration {dur:.1f}s exceeds "
                            f"threshold {threshold:.1f}s",
                            f"scene_index={idx}, duration_seconds={dur:.1f}, "
                            f"threshold={threshold:.1f}, asset_type=still_image, "
                            f"motion_type=static",
                            "medium",
                            scene_index=idx,
                            duration_seconds=dur,
                            threshold_seconds=threshold,
                            asset_type="still_image",
                            motion_type="static",
                        )
                    )
                else:
                    results.append(
                        self._pass(
                            "IMG_007",
                            f"Scene {idx} static-hold duration within cap",
                            f"{dur:.1f}s",
                            scene_index=idx,
                        )
                    )

            # IMG_008: Brightness floor for warmth/intimacy scenes
            if self._config.is_enabled("IMG_008") and img_path.exists():
                raw_meta = scene.get("visual_metadata", {})
                mood = ""
                if isinstance(raw_meta, dict):
                    mood = str(raw_meta.get("mood", "")).upper()

                if mood in _WARMTH_INTIMACY_MOODS:
                    luminance = _avg_luminance(img_path)
                    threshold = self._config.image_brightness_min_luminance
                    if luminance is not None and luminance < threshold:
                        results.append(
                            self._warn(
                                "IMG_008",
                                f"Scene {idx}: warmth/intimacy scene ({mood}) "
                                f"luminance {luminance:.1f} below floor {threshold:.1f}",
                                f"scene_index={idx}, mood={mood}, "
                                f"avg_luminance={luminance:.1f}, threshold={threshold:.1f}",
                                "medium",
                                scene_index=idx,
                                mood=mood,
                                avg_luminance=luminance,
                                threshold=threshold,
                            )
                        )
                    else:
                        measured = (
                            f"{luminance:.1f}" if luminance is not None else "n/a"
                        )
                        results.append(
                            self._pass(
                                "IMG_008",
                                f"Scene {idx} brightness floor satisfied",
                                f"luminance={measured}, mood={mood}",
                                scene_index=idx,
                            )
                        )
                else:
                    results.append(
                        self._skip(
                            "IMG_008",
                            f"scene_index={idx}, mood={mood or 'none'} "
                            f"(not warmth/intimacy)",
                            scene_index=idx,
                        )
                    )

        # IMG_004: No repeated visual prompts across generated scenes
        if self._config.is_enabled("IMG_004"):
            if len(prompts) < 2:
                results.append(
                    self._skip("IMG_004", "fewer than 2 generated scenes with prompts")
                )
            else:
                threshold = self._config.image_prompt_similarity_threshold
                repeated: list[tuple[int, int, float]] = []
                for i in range(len(prompts)):
                    for j in range(i + 1, len(prompts)):
                        sim = _jaccard(prompts[i][1], prompts[j][1])
                        if sim >= threshold:
                            repeated.append(
                                (prompts[i][0], prompts[j][0], round(sim, 2))
                            )
                if repeated:
                    evidence = "; ".join(
                        f"scenes {a}&{b} sim={s}" for a, b, s in repeated[:3]
                    )
                    results.append(
                        self._warn(
                            "IMG_004",
                            f"{len(repeated)} pair(s) of visually similar prompts detected",
                            evidence,
                            "medium",
                            repeated_pair_count=len(repeated),
                        )
                    )
                else:
                    results.append(
                        self._pass("IMG_004", "No repeated visual prompts detected")
                    )

        return results
