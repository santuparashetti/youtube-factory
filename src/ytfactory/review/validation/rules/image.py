"""Image validation rules (category D).

Rules:
  IMG_001 [critical] — Image file exists for every generated scene
  IMG_002 [high]     — Image file meets minimum size
  IMG_003 [high]     — Visual prompt is present for every generated scene
  IMG_004 [medium]   — No repeated visual prompts (Jaccard similarity)
  IMG_005 [low]      — Shot type assigned (V4 shot-type coverage)
  IMG_006 [medium]   — Visual prompt contains at least one style marker
"""

from __future__ import annotations

from pathlib import Path

from ytfactory.review.validation.framework import BaseValidator
from ytfactory.review.validation.models import ValidationResult


def _jaccard(a: str, b: str) -> float:
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


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
            s for s in scenes
            if s.get("scene_type", "generated_image") == "generated_image"
        ]

        if not scenes:
            for rule_id in ("IMG_001", "IMG_002", "IMG_003", "IMG_004", "IMG_005", "IMG_006"):
                if self._config.is_enabled(rule_id):
                    results.append(self._skip(rule_id, "no scenes available"))
            return results

        prompts: list[tuple[int, str]] = []  # (index, visual_prompt)

        for scene in generated:
            idx = scene.get("index", 0)
            img_path = project_dir / "images" / f"scene-{idx:03d}.png"

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
                        self._pass("IMG_001", f"Scene {idx} image exists", img_path.name, scene_index=idx)
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

            visual_prompt = scene.get("visual_prompt", "")

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

        # IMG_004: No repeated visual prompts across generated scenes
        if self._config.is_enabled("IMG_004"):
            if len(prompts) < 2:
                results.append(self._skip("IMG_004", "fewer than 2 generated scenes with prompts"))
            else:
                threshold = self._config.image_prompt_similarity_threshold
                repeated: list[tuple[int, int, float]] = []
                for i in range(len(prompts)):
                    for j in range(i + 1, len(prompts)):
                        sim = _jaccard(prompts[i][1], prompts[j][1])
                        if sim >= threshold:
                            repeated.append((prompts[i][0], prompts[j][0], round(sim, 2)))
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
                    results.append(self._pass("IMG_004", "No repeated visual prompts detected"))

        return results
