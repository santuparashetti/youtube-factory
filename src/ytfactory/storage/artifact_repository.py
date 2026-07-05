from __future__ import annotations

import json
from pathlib import Path

from ytfactory.shared.constants import WORKSPACE_DIR


class ArtifactRepository:
    """Repository for project artifacts."""

    def _stage_path(
        self,
        project_id: str,
        stage: str,
    ) -> Path:
        return Path(WORKSPACE_DIR) / project_id / stage

    def write_json(
        self,
        project_id: str,
        stage: str,
        filename: str,
        data: dict | list,
    ) -> Path:
        directory = self._stage_path(project_id, stage)
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                indent=2,
                ensure_ascii=False,
            )

        return path

    def write_markdown(
        self,
        project_id: str,
        stage: str,
        filename: str,
        content: str,
    ) -> Path:
        directory = self._stage_path(project_id, stage)
        directory.mkdir(parents=True, exist_ok=True)

        path = directory / filename

        path.write_text(
            content,
            encoding="utf-8",
        )

        return path

    def read_json(
        self,
        project_id: str,
        stage: str,
        filename: str,
    ) -> dict:
        path = self._stage_path(project_id, stage) / filename

        with open(path, encoding="utf-8") as f:
            return json.load(f)
