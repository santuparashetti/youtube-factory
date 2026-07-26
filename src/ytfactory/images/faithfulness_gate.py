"""Faithfulness pre-render gate — summarizes per-scene faithfulness QA results.

Reads faithfulness_qa.status from every scene (set by the per-scene retry loop
in scene_planner_node) and reports PASS/FAILED/SKIPPED counts. Never blocks the
pipeline — failures are logged and written to phase1_report.json so a human can
decide, since these are recoverable in Phase 2 by manually fixing the image
prompt. See docs/script/task-2.2-retry-engine-reliability.md Phase 6.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from ytfactory.scenes.models import FaithfulnessStatus


@dataclass
class FaithfulnessGateResult:
    """Summary of the faithfulness gate evaluation across all scenes."""

    passed: bool
    passed_count: int
    failed_count: int
    skipped_count: int
    failed_scenes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "failed_scenes": self.failed_scenes,
        }


def evaluate_faithfulness_gate(scenes: list[dict]) -> FaithfulnessGateResult:
    """Evaluate the faithfulness gate over a scene list (dicts from scene-plan.json)."""
    failed_scenes: list[dict] = []
    passed_count = 0
    skipped_count = 0

    for scene in scenes:
        qa = scene.get("faithfulness_qa") or {}
        status = qa.get("status")
        if status == FaithfulnessStatus.FAILED.value:
            failed_scenes.append(
                {
                    "index": scene.get("index"),
                    "title": scene.get("title", ""),
                    "violation": qa.get("violation", ""),
                    "attempts": qa.get("attempts", 0),
                    "critical_errors": qa.get("critical_errors", []),
                }
            )
        elif status == FaithfulnessStatus.SKIPPED.value:
            skipped_count += 1
        elif status == FaithfulnessStatus.PASS.value:
            passed_count += 1

    gate_pass = len(failed_scenes) == 0

    logger.info(
        "Faithfulness gate: {} PASS, {} FAILED, {} SKIPPED (brand)",
        passed_count,
        len(failed_scenes),
        skipped_count,
    )
    if failed_scenes:
        for s in failed_scenes:
            logger.error(
                "  Scene {:03d} FAILED — {}",
                s["index"],
                s["violation"],
            )

    return FaithfulnessGateResult(
        passed=gate_pass,
        passed_count=passed_count,
        failed_count=len(failed_scenes),
        skipped_count=skipped_count,
        failed_scenes=failed_scenes,
    )
