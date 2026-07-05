from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.scenes.planner.gemini_planner import GeminiScenePlanner
from ytfactory.scenes.repository.scene_repository import SceneRepository
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.storage.project_repository import ProjectRepository


class ScenePipeline:
    """Generate scene plan from an imported script."""

    def __init__(self, settings: Settings):
        self._projects = ProjectRepository()
        self._planner = GeminiScenePlanner(settings)
        self._repository = SceneRepository()

    def run(self, project_id: str) -> None:
        project = self._projects.load(project_id)

        project_dir = Path(WORKSPACE_DIR) / project.id

        script_file = project_dir / "script" / "script.md"

        if not script_file.exists():
            raise FileNotFoundError("Script not found. Run 'import-script' first.")

        script = script_file.read_text(encoding="utf-8")

        scene_plan = self._planner.generate(script)

        self._repository.save(project_dir, scene_plan)

        self._projects.update_stage(
            project.id,
            "scenes",
            "completed",
        )
