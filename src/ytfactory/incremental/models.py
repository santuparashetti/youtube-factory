"""Domain models for the Incremental Rendering & Scene Workspace V1."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SceneState(str, Enum):
    """Approval state of a single scene in the workspace."""

    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    NEEDS_REVISION = "needs_revision"
    APPROVED = "approved"
    LOCKED = "locked"


@dataclass
class ManifestEntry:
    """Record for a single pipeline artifact tracked in the manifest."""

    stage: str
    path: str
    checksum: str
    mtime: float
    generated_at: str
    engine_version: str = "1"


@dataclass
class ChangeReport:
    """Summary of changes detected between the current workspace and the manifest."""

    changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    invalidated_stages: set[str] = field(default_factory=set)

    @property
    def has_changes(self) -> bool:
        return bool(self.changed or self.missing or self.new)
