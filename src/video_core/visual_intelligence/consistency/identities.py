"""Visual Identity domain model for consistency tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class IdentityType(str, Enum):
    CHARACTER = "Character"
    OBJECT = "Object"
    ANIMAL = "Animal"
    BUILDING = "Building"
    ENVIRONMENT = "Environment"
    SYMBOL = "Symbol"


@dataclass
class VisualIdentity:
    """Canonical description of a recurring visual entity."""

    identity_id: str
    identity_type: IdentityType
    display_name: str = ""
    description: str = ""
    canonical_attributes: dict[str, Any] = field(default_factory=dict)
    reference_image_paths: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_prompt_fragment(self) -> str:
        parts = [f"{self.display_name} ({self.identity_type.value})"]
        if self.canonical_attributes:
            attr_parts = []
            for key, val in self.canonical_attributes.items():
                if val:
                    attr_parts.append(f"{key}: {val}")
            if attr_parts:
                parts.append(", ".join(attr_parts))
        return ", ".join(parts)
