import json
from dataclasses import asdict
from pathlib import Path

from ytfactory.images.models import (
    ImageArtifact,
    ImageManifest,
)


class ImageRepository:
    """Persist image generation artifacts."""

    def save_manifest(
        self,
        output_dir: Path,
        manifest: ImageManifest,
    ) -> None:

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        data = asdict(manifest)

        # Convert Path objects to strings
        for image in data["images"]:
            image["path"] = str(image["path"])

        with open(
            output_dir / "images.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                data,
                f,
                indent=2,
            )

    def list_images(
        self,
        output_dir: Path,
    ) -> list[ImageArtifact]:

        manifest_file = output_dir / "images.json"

        if not manifest_file.exists():
            return []

        with open(
            manifest_file,
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        return [
            ImageArtifact(
                scene_index=item["scene_index"],
                prompt=item["prompt"],
                filename=item["filename"],
                path=Path(item["path"]),
            )
            for item in data["images"]
        ]