from pathlib import Path

from ytfactory.scenes.models import ScenePlan


class SceneRepository:
    """Persist generated scene plans."""

    def save(
        self,
        project_dir: Path,
        scene_plan: ScenePlan,
    ) -> None:
        scenes_dir = project_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)

        (scenes_dir / "scene-plan.json").write_text(
            scene_plan.model_dump_json(indent=2),
            encoding="utf-8",
        )

        markdown = self._to_markdown(scene_plan)

        (scenes_dir / "scene-plan.md").write_text(
            markdown,
            encoding="utf-8",
        )

    def _to_markdown(self, scene_plan: ScenePlan) -> str:
        lines: list[str] = []

        lines.append(f"# {scene_plan.title}")
        lines.append("")

        for scene in scene_plan.scenes:
            lines.append(f"## Scene {scene.index}: {scene.title}")
            lines.append("")
            lines.append(f"**Duration:** {scene.duration_seconds} seconds")
            lines.append("")
            lines.append("### Narration")
            lines.append(scene.narration)
            lines.append("")
            lines.append("### Visual Prompt")
            lines.append(scene.visual_prompt)
            lines.append("")

        return "\n".join(lines)