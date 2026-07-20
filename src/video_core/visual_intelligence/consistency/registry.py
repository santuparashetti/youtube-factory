"""Visual Identity Registry — manages recurring character and object profiles."""

from __future__ import annotations

from typing import Any

from video_core.visual_intelligence.consistency.identities import IdentityType, VisualIdentity


class IdentityRegistry:
    """Central registry of visual identities.

    Data-driven: identities are loaded from configuration, not hardcoded.
    """

    def __init__(self) -> None:
        self._identities: dict[str, VisualIdentity] = {}

    def register(self, identity: VisualIdentity) -> None:
        self._identities[identity.identity_id] = identity
        identity.updated_at = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat()

    def get(self, identity_id: str) -> VisualIdentity | None:
        return self._identities.get(identity_id)

    def find_by_name(self, name: str) -> VisualIdentity | None:
        for identity in self._identities.values():
            if identity.display_name.lower() == name.lower():
                return identity
        return None

    def find_by_type(self, identity_type: IdentityType) -> list[VisualIdentity]:
        return [i for i in self._identities.values() if i.identity_type == identity_type]

    def all_identities(self) -> list[VisualIdentity]:
        return list(self._identities.values())

    def load_from_config(self, config: dict[str, Any]) -> None:
        for identity_id, data in config.items():
            type_str = data.get("identity_type", "Character")
            try:
                identity_type = IdentityType(type_str)
            except ValueError:
                identity_type = IdentityType.CHARACTER
            self.register(
                VisualIdentity(
                    identity_id=identity_id,
                    identity_type=identity_type,
                    display_name=data.get("display_name", identity_id),
                    description=data.get("description", ""),
                    canonical_attributes=data.get("canonical_attributes", {}),
                    reference_image_paths=data.get("reference_image_paths", []),
                )
            )
