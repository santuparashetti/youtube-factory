from pathlib import Path

from ytfactory.config.settings import Settings
from ytfactory.providers.image.base import ImageProvider


class ComfyUIImageProvider(ImageProvider):
    """ComfyUI image provider."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def generate(
        self,
        prompt: str,
        output_path: Path,
        *,
        width: int = 1280,
        height: int = 720,
    ) -> Path:
        raise NotImplementedError(
            "ComfyUI provider not implemented yet."
        )