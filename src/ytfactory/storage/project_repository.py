from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from ytfactory.domain.project import Project
from ytfactory.shared.constants import (
    PROJECT_FILE,
    WORKSPACE_DIR,
)


class ProjectRepository:
    """Repository for project metadata."""

    def _project_path(self, project_id: str) -> Path:
        return Path(WORKSPACE_DIR) / project_id

    def load(self, project_id: str) -> Project:
        path = self._project_path(project_id) / PROJECT_FILE

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        return Project(**data)

    def save(self, project: Project) -> None:
        root = self._project_path(project.id)
        root.mkdir(parents=True, exist_ok=True)

        with open(root / PROJECT_FILE, "w", encoding="utf-8") as f:
            json.dump(
                asdict(project),
                f,
                indent=2,
            )

    def update_stage(
        self,
        project_id: str,
        stage: str,
        status: str,
    ) -> Project:
        project = self.load(project_id)

        project.stages[stage]["status"] = status

        self.save(project)

        return project