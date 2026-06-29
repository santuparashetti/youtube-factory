from __future__ import annotations

import json

from .models import CaptionArtifact


class CaptionRepository:

    def save(
        self,
        artifact: CaptionArtifact,
    ) -> None:

        manifest = (
            artifact.srt_path.parent
            / "captions.json"
        )

        data = []

        if manifest.exists():
            data = json.loads(
                manifest.read_text(
                    encoding="utf-8",
                )
            )

        data.append(
            {
                "scene_id": artifact.scene_id,
                "subtitle": str(artifact.srt_path),
            }
        )

        manifest.write_text(
            json.dumps(
                data,
                indent=2,
            ),
            encoding="utf-8",
        )