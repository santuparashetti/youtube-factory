"""SceneManifestGenerator — export a generic per-scene manifest for downstream factories.

Reads:
  - scenes/scene-plan.json      → narration, duration_seconds, scene index
  - audio/scene-NNN.timing.json → real duration (last entry's "end"); falls back
                                   to declared duration_seconds

Output: publish/scene-manifest.json — a stable, generic shape:
  [{"image_path": str, "audio_path": str, "narration_text": str,
    "duration_seconds": float}, ...]

Intended consumer: shorts_factory (and any other factory that needs to
recompose from ytfactory's per-scene assets without importing ytfactory's
internal schema).  Paths in the manifest are absolute so the consumer can
read them from any working directory.
"""

from __future__ import annotations

import json
from pathlib import Path

from ytfactory.publish.artifacts import scene_manifest_path
from ytfactory.shared.constants import WORKSPACE_DIR


def _real_duration(project_dir: Path, scene: dict) -> float:
    """Return real audio duration for a scene, falling back to declared duration."""
    index = scene["index"]
    timing_file = project_dir / "audio" / f"scene-{index:03d}.timing.json"
    if timing_file.exists():
        try:
            data = json.loads(timing_file.read_text(encoding="utf-8"))
            if data:
                return float(data[-1]["end"])
        except (json.JSONDecodeError, KeyError, IndexError, ValueError):
            pass
    return float(scene.get("duration_seconds", 0.0))


class SceneManifestGenerator:
    """Export a generic per-scene manifest for use by downstream factories."""

    def generate(self, project_id: str) -> list[dict]:
        """Build and write scene-manifest.json. Returns the manifest entries."""
        project_dir = Path(WORKSPACE_DIR) / project_id
        plan_file = project_dir / "scenes" / "scene-plan.json"
        data = json.loads(plan_file.read_text(encoding="utf-8"))
        scenes = data.get("scenes", [])

        entries = [
            {
                "image_path": str(
                    (project_dir / "images" / f"scene-{s['index']:03d}.png").resolve()
                ),
                "audio_path": str(
                    (project_dir / "audio" / f"scene-{s['index']:03d}.mp3").resolve()
                ),
                "narration_text": s["narration"],
                "duration_seconds": _real_duration(project_dir, s),
            }
            for s in scenes
        ]

        out = scene_manifest_path(project_id)
        out.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
        return entries
