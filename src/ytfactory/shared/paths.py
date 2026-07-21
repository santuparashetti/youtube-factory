"""Shared path helpers — safe project_dir resolution with traversal guards."""

from __future__ import annotations

import re

from pathlib import Path

_VALID_PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def safe_project_dir(project_id: str, workspace_dir: str = "workspace/jobs") -> Path:
    """
    Resolve a project directory inside the workspace with a strict allowlist
    on project_id and an escape-path check.

    This prevents path traversal such as:
        project_id="../../../etc"
    """
    if not _VALID_PROJECT_ID_RE.match(project_id):
        raise ValueError(
            f"Invalid project_id {project_id!r}. "
            "Expected alphanumeric characters, hyphens, or underscores only."
        )

    resolved = (Path(workspace_dir) / project_id).resolve()
    allowed = Path(workspace_dir).resolve()

    if not str(resolved).startswith(str(allowed) + "/"):
        raise ValueError(
            f"Project path escapes workspace: {resolved}"
        )

    return resolved
