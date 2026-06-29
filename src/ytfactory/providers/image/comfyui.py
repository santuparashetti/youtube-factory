from ytfactory.config.settings import Settings
from ytfactory.domain.image import (
    ImageRequest,
    ImageResponse,
)
from ytfactory.providers.image.base import ImageProvider


class ComfyUIImageProvider(ImageProvider):
    """ComfyUI image provider."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def generate(
        self,
        request: ImageRequest,
    ) -> ImageResponse:
        """
        Generate an image using ComfyUI.

        NOTE:
        This is currently a placeholder implementation.
        The actual HTTP integration with ComfyUI will be
        implemented in the next step.
        """

        raise NotImplementedError(
            "ComfyUI image generation is not implemented yet."
        )