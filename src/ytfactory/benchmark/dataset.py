"""Benchmark dataset loader — reads benchmark.yaml."""

from __future__ import annotations

from pathlib import Path

from .models import BenchmarkScene


class BenchmarkDataset:
    """Parsed benchmark.yaml dataset.

    Schema (minimum required fields per scene):
        scenes:
          - id: scene-002
            image: images/scene-002.png
            expected_failures:
              - hands_invalid
            visual_prompt: "..."   # optional — passed to VisionProvider
            notes: "..."           # optional — human annotation

    Good scenes (no expected failures) are included with an empty list.
    """

    def __init__(self, path: Path, scenes: list[BenchmarkScene]) -> None:
        self.path = path
        self.scenes = scenes

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path) -> "BenchmarkDataset":
        """Load and validate benchmark.yaml from *path*."""
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required for benchmark datasets. "
                "Install it with: uv add pyyaml"
            ) from exc

        if not path.exists():
            raise FileNotFoundError(f"Benchmark dataset not found: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        base = path.parent
        scenes: list[BenchmarkScene] = []

        for entry in data.get("scenes") or []:
            image_path = base / entry["image"]
            scenes.append(
                BenchmarkScene(
                    id=str(entry["id"]),
                    image=image_path,
                    expected_failures=list(entry.get("expected_failures") or []),
                    visual_prompt=str(entry.get("visual_prompt") or ""),
                    notes=str(entry.get("notes") or ""),
                )
            )

        return cls(path=path, scenes=scenes)

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def bad_scenes(self) -> list[BenchmarkScene]:
        return [s for s in self.scenes if s.is_bad]

    @property
    def good_scenes(self) -> list[BenchmarkScene]:
        return [s for s in self.scenes if not s.is_bad]
