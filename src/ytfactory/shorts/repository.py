"""File I/O for all Shorts workspace artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.shorts.models import (
    OpportunityExtractionResult,
    ShortsImageManifest,
    ShortsScenePlan,
    ShortsScript,
    ValidationReport,
)
from ytfactory.shared.constants import WORKSPACE_DIR


class ShortsRepository:
    def shorts_dir(self, project_id: str) -> Path:
        return Path(WORKSPACE_DIR) / project_id / "shorts"

    def short_dir(self, project_id: str, short_id: str) -> Path:
        return self.shorts_dir(project_id) / short_id

    # ── Opportunities ──────────────────────────────────────────────────────

    def save_opportunities(
        self, project_id: str, result: OpportunityExtractionResult
    ) -> None:
        path = self.shorts_dir(project_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "opportunities.json").write_text(
            json.dumps(result.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_opportunities(
        self, project_id: str
    ) -> OpportunityExtractionResult | None:
        path = self.shorts_dir(project_id) / "opportunities.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return OpportunityExtractionResult.model_validate(data)

    # ── Script ─────────────────────────────────────────────────────────────

    def save_script(
        self, project_id: str, short_id: str, script: ShortsScript
    ) -> None:
        d = self.short_dir(project_id, short_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "short-script.json").write_text(
            json.dumps(script.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (d / "short-script.md").write_text(
            _script_to_markdown(script), encoding="utf-8"
        )

    def load_script(self, project_id: str, short_id: str) -> ShortsScript | None:
        path = self.short_dir(project_id, short_id) / "short-script.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ShortsScript.model_validate(data)

    # ── Validation report ──────────────────────────────────────────────────

    def save_validation_report(
        self, project_id: str, short_id: str, report: ValidationReport
    ) -> None:
        d = self.short_dir(project_id, short_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "validation-report.json").write_text(
            json.dumps(report.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_validation_report(
        self, project_id: str, short_id: str
    ) -> ValidationReport | None:
        path = self.short_dir(project_id, short_id) / "validation-report.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ValidationReport.model_validate(data)

    # ── Scene plan ─────────────────────────────────────────────────────────

    def save_scene_plan(
        self, project_id: str, short_id: str, plan: ShortsScenePlan
    ) -> None:
        d = self.short_dir(project_id, short_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "scene-plan.json").write_text(
            json.dumps(plan.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (d / "scene-plan.md").write_text(
            _scene_plan_to_markdown(plan), encoding="utf-8"
        )

    def load_scene_plan(
        self, project_id: str, short_id: str
    ) -> ShortsScenePlan | None:
        path = self.short_dir(project_id, short_id) / "scene-plan.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ShortsScenePlan.model_validate(data)

    # ── Image manifest ─────────────────────────────────────────────────────

    def ensure_images_dir(self, project_id: str, short_id: str) -> Path:
        d = self.short_dir(project_id, short_id) / "images"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_image_manifest(
        self, project_id: str, short_id: str, manifest: ShortsImageManifest
    ) -> None:
        d = self.ensure_images_dir(project_id, short_id)
        (d / "image-prompts.json").write_text(
            json.dumps(manifest.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_image_manifest(
        self, project_id: str, short_id: str
    ) -> ShortsImageManifest | None:
        path = self.short_dir(project_id, short_id) / "images" / "image-prompts.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return ShortsImageManifest.model_validate(data)

    # ── Stale artifact cleanup (force-regeneration support) ────────────────

    def delete_short_artifacts(self, project_id: str, short_id: str) -> None:
        """Remove all artifacts for one Short so force-regeneration starts clean."""
        import shutil
        d = self.short_dir(project_id, short_id)
        if d.exists():
            shutil.rmtree(d)


# ── Markdown helpers ──────────────────────────────────────────────────────────

def _script_to_markdown(script: ShortsScript) -> str:
    lines = [
        f"# {script.title}",
        "",
        f"**Short ID:** {script.short_id}  ",
        f"**Parent video:** {script.parent_video_id}  ",
        f"**Angle:** {script.angle}  ",
        f"**Target duration:** {script.target_duration_seconds:.0f}s  ",
        f"**Word count:** ~{script.estimated_word_count}  ",
        f"**Validation:** {'PASS' if script.validation_passed else 'FAIL'}",
        "",
        "---",
        "",
        "## HOOK (0–3 sec)",
        "",
        script.hook,
        "",
        "## SETUP (3–10 sec)",
        "",
        script.setup,
        "",
        "## STORY (10–35 sec)",
        "",
        script.story,
        "",
        "## REVELATION (35–50 sec)",
        "",
        script.revelation,
        "",
        "## OPEN LOOP (50–60 sec)",
        "",
        script.open_loop,
        "",
        "---",
        "",
        "## Long-form Bridge",
        "",
        f"**Relationship:** {script.long_form_bridge.relationship}  ",
        f"**Bridge type:** {script.long_form_bridge.bridge_type}  ",
        f"**Unresolved question:** {script.long_form_bridge.unresolved_question}  ",
        f"**Continuation value:** {script.long_form_bridge.continuation_value}",
    ]
    if script.scores:
        lines += ["", "## Quality Scores", ""]
        for k, v in script.scores.model_dump().items():
            lines.append(f"- **{k}:** {v}")
    return "\n".join(lines)


def _scene_plan_to_markdown(plan: ShortsScenePlan) -> str:
    lines = [
        f"# Scene Plan — {plan.short_id}",
        "",
        f"**Aspect ratio:** {plan.aspect_ratio}  ",
        f"**Resolution:** {plan.resolution.width}×{plan.resolution.height}  ",
        f"**Scene count:** {plan.scene_count}  ",
        f"**Total duration:** {plan.total_estimated_duration:.1f}s",
        "",
        f"**Visual hook:** {plan.visual_hook_description}",
        "",
        "---",
        "",
    ]
    for scene in plan.scenes:
        hook_note = " 🎯 HOOK" if scene.is_hook_scene else ""
        lines += [
            f"## Scene {scene.index:02d} — {scene.section.upper()}{hook_note}",
            "",
            f"**Duration:** {scene.duration_seconds:.1f}s  ",
            f"**Shot type:** {scene.shot_type}",
            "",
            "**Narration:**",
            scene.narration,
            "",
            "**Visual prompt:**",
            scene.visual_prompt,
            "",
        ]
    return "\n".join(lines)
