from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.scenes.planner.llm_planner import LLMScenePlanner
from ytfactory.scenes.repository.scene_repository import SceneRepository
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.pipeline_status import get_writer
from ytfactory.shared.script_utils import strip_script_heading
from ytfactory.storage.project_repository import ProjectRepository


class ScenePipeline:
    """Generate scene plan from an imported script."""

    def __init__(self, settings: Settings):
        self._projects = ProjectRepository()
        self._planner = LLMScenePlanner(settings)
        self._repository = SceneRepository()

    def run(self, project_id: str) -> None:
        project = self._projects.load(project_id)

        project_dir = Path(WORKSPACE_DIR) / project.id

        script_file = project_dir / "script" / "script.md"

        if not script_file.exists():
            raise FileNotFoundError("Script not found. Run 'import-script' first.")

        script = script_file.read_text(encoding="utf-8")
        # Strip any leading H1 title heading — it is a structural label, not narration.
        script, heading = strip_script_heading(script)

        _w = get_writer()
        if _w:
            _w.stage_start("scene_planning")

        scene_plan = self._planner.generate(script)

        # Defensive post-process: if the LLM still included the heading text at the
        # start of scene 1's narration, strip it.  This covers cases where the model
        # treats the heading as part of the script body despite the system prompt rule.
        if heading:
            heading_text = heading.strip()
            for scene in scene_plan.get("scenes", []):
                narration = scene.get("narration", "")
                if narration.startswith(heading_text):
                    scene["narration"] = narration[len(heading_text):].lstrip(" ,.:;")

        self._repository.save(project_dir, scene_plan)

        if _w:
            _w.stage_complete()

        self._projects.update_stage(
            project.id,
            "scenes",
            "completed",
        )
