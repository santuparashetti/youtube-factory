from pathlib import Path

from ytfactory.scenes.models import ScenePlan
from ytfactory.shared.constants import WORKSPACE_DIR


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

    def save_scenes(
        self,
        project_dir: Path,
        scenes: list[dict],
        extra: dict | None = None,
    ) -> None:
        """Persist an enriched scene list to scene-plan.json.

        Preserves the existing on-disk JSON format/schema. Merges ``scenes``
        into the existing document under the ``scenes`` key and updates
        ``total_duration_seconds`` when not supplied in ``extra``.
        """
        import json

        scenes_dir = project_dir / "scenes"
        scenes_dir.mkdir(parents=True, exist_ok=True)

        path = scenes_dir / "scene-plan.json"
        existing: dict = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        existing["scenes"] = scenes
        if extra:
            existing.update(extra)
        if "total_duration_seconds" not in existing:
            existing["total_duration_seconds"] = sum(
                s.get("duration_seconds", 0) for s in scenes
            )

        path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def load_scenes(self, project_dir: Path) -> list[dict]:
        """Load the scene list from scene-plan.json."""
        import json

        path = project_dir / "scenes" / "scene-plan.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("scenes", [])
        except (json.JSONDecodeError, OSError):
            return []

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
