"""Phase 1.5 Image QA Gate — verify placed images against visual_prompt
before Phase 2 renders. docs/script/task-2.10-phase1.5-image-qa.md.

Deviation from the doc: it assumed a custom `vision_client.verify(image_b64,
prompt, max_tokens)` -> raw-text interface. This codebase's real
VisionProvider.review(image_path, visual_prompt, scene_context) already
returns a structured VisionReviewResult (status/recommend_regeneration/
issues) via the existing LAMM-backed vision stack (local Qwen2.5-VL, mock,
etc.) — reused here instead of inventing a second, parallel vision API.
`_parse_qa_response()` is kept as a plain-text fallback parser (used when a
provider's raw_response needs re-parsing) and is independently tested per
the doc's spec.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class QADecision(str, Enum):
    KEEP = "keep"
    REGENERATE = "regenerate"
    MISSING = "missing"
    ERROR = "error"


@dataclass
class SceneQAResult:
    scene_id: int
    filename: str
    decision: QADecision
    reasons: list[str]
    visual_prompt: str
    shot_type: str


def _parse_qa_response(response: str) -> tuple[QADecision, list[str]]:
    """Parse a KEEP / REGENERATE plain-text response. Never blocks — an
    ambiguous response defaults to KEEP."""
    text = response.strip()
    if text.upper().startswith("KEEP"):
        return QADecision.KEEP, []

    if text.upper().startswith("REGENERATE"):
        reasons = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                reasons.append(line[2:].strip())
        return QADecision.REGENERATE, reasons[:3]

    logger.warning("QA response parse ambiguous: %s — defaulting to KEEP", text[:100])
    return QADecision.KEEP, []


def verify_scene(scene: dict, images_dir: Path, vision_provider) -> SceneQAResult:
    """Verify one scene image against its visual_prompt via VisionProvider.review()."""
    scene_id = scene["scene_id"]
    filename = scene["expected_filename"]
    visual_prompt = scene["visual_prompt"]
    shot_type = scene.get("shot_type", "unspecified")
    scene_type = scene.get("scene_type", "")
    image_path = images_dir / filename

    if scene_type == "brand_card":
        return SceneQAResult(scene_id, filename, QADecision.KEEP, [], visual_prompt, shot_type)

    if not image_path.is_file() or image_path.stat().st_size < 1000:
        return SceneQAResult(
            scene_id, filename, QADecision.MISSING,
            ["Image file not found or too small"], visual_prompt, shot_type,
        )

    try:
        result = vision_provider.review(
            image_path=image_path,
            visual_prompt=visual_prompt,
            scene_context={"scene_id": scene_id, "shot_type": shot_type},
        )
        if result.status == "ERROR":
            logger.warning("Scene %03d QA error: %s — defaulting to KEEP", scene_id, result.error)
            return SceneQAResult(scene_id, filename, QADecision.KEEP, [], visual_prompt, shot_type)

        decision = QADecision.REGENERATE if result.recommend_regeneration else QADecision.KEEP
        reasons = [i.description for i in result.issues][:3]
    except Exception as exc:
        logger.warning("Scene %03d QA error: %s — defaulting to KEEP", scene_id, exc)
        return SceneQAResult(scene_id, filename, QADecision.KEEP, [], visual_prompt, shot_type)

    return SceneQAResult(scene_id, filename, decision, reasons, visual_prompt, shot_type)


def verify_all_scenes(
    manifest_path: Path,
    images_dir: Path,
    vision_provider,
    scene_filter: list[int] | None = None,
) -> list[SceneQAResult]:
    """Verify all (or filtered) scenes in the manifest."""
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    scenes = manifest["scenes"]
    if scene_filter:
        scenes = [s for s in scenes if s["scene_id"] in scene_filter]

    results = []
    for scene in scenes:
        result = verify_scene(scene, images_dir, vision_provider)
        _log_result(result)
        results.append(result)
    return results


def _log_result(result: SceneQAResult) -> None:
    icons = {
        QADecision.KEEP: "✓",
        QADecision.REGENERATE: "✗",
        QADecision.MISSING: "?",
        QADecision.ERROR: "!",
    }
    icon = icons[result.decision]
    msg = f"  Scene {result.scene_id:03d} | {icon} {result.decision.upper():12s} | {result.filename}"
    if result.reasons:
        for r in result.reasons:
            msg += f"\n              → {r}"
    print(msg)


def write_qa_report(results: list[SceneQAResult], output_path: Path) -> dict:
    keep = [r for r in results if r.decision == QADecision.KEEP]
    regen = [r for r in results if r.decision == QADecision.REGENERATE]
    missing = [r for r in results if r.decision == QADecision.MISSING]

    report = {
        "summary": {
            "total": len(results),
            "keep": len(keep),
            "regenerate": len(regen),
            "missing": len(missing),
        },
        "scenes": [
            {
                "scene_id": r.scene_id,
                "filename": r.filename,
                "decision": r.decision.value,
                "reasons": r.reasons,
            }
            for r in results
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return report
