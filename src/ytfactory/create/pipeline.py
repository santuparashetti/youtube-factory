from pathlib import Path

from slugify import slugify

from ytfactory.domain.project import Project
from ytfactory.shared.constants import (
    PROJECT_STAGES,
    WORKSPACE_DIR,
)
from ytfactory.storage.project_repository import ProjectRepository


class CreatePipeline:
    """Create a new YouTube Factory project."""

    def __init__(self) -> None:
        self._repository = ProjectRepository()

    def run(self, title: str) -> Project:
        slug = slugify(title)

        project = Project(
            id=slug,
            title=title,
        )

        root = Path(WORKSPACE_DIR) / slug
        root.mkdir(parents=True, exist_ok=True)

        for stage in PROJECT_STAGES:
            (root / stage).mkdir(exist_ok=True)

        self._repository.save(project)

        return project