from ytfactory.config.settings import Settings
from ytfactory.domain.image import (
    ImageRequest,
    ImageResponse,
)
from ytfactory.providers.image.base import ImageProvider


class GeminiImageProvider(ImageProvider):
    """Gemini image generation provider."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def generate(
        self,
        request: ImageRequest,
    ) -> ImageResponse:
        raise NotImplementedError(
            "Gemini image generation is not implemented yet."
        )