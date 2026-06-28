from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from slugify import slugify

from ytfactory.create.models import Project
from ytfactory.shared.constants import (
    PROJECT_FILE,
    PROJECT_STAGES,
    WORKSPACE_DIR,
)


class CreatePipeline:
    """Create a new YouTube Factory project."""

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

        with open(root / PROJECT_FILE, "w", encoding="utf-8") as f:
            json.dump(
                asdict(project),
                f,
                indent=2,
            )

        return project