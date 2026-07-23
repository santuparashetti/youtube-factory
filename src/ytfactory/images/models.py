from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ImageArtifact:
    """Generated image for a scene."""

    scene_index: int

    prompt: str

    filename: str

    path: Path

    qa_status: str = ""
    qa_score: float = 0.0
    qa_failure_reason: str = ""


@dataclass(slots=True)
class ImageManifest:
    """Collection of generated images."""

    images: list[ImageArtifact] = field(
        default_factory=list,
    )


@dataclass(slots=True)
class ImageGenerationResult:
    """Pipeline output."""

    manifest: ImageManifest

    output_directory: Path
