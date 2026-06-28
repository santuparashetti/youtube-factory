from pathlib import Path

from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository


class ImportScriptPipeline:

    def __init__(self):
        self.projects = ProjectRepository()
        self.artifacts = ArtifactRepository()

    def run(
        self,
        project_id: str,
        script_file: Path,
    ) -> None:

        project = self.projects.load(project_id)

        content = script_file.read_text(encoding="utf-8")

        self.projects.update_stage(
            project.id,
            "script",
            "running",
        )

        self.artifacts.write_markdown(
            project.id,
            "script",
            "script.md",
            content,
        )

        self.artifacts.write_json(
            project.id,
            "script",
            "script.json",
            {
                "title": project.title,
                "content": content,
            },
        )

        self.projects.update_stage(
            project.id,
            "script",
            "completed",
        )