from abc import ABC, abstractmethod

from video_core.domain.image import (
    ImageRequest,
    ImageResponse,
)


class ImageProvider(ABC):
    """Base interface for all image providers."""

    @abstractmethod
    def generate(
        self,
        request: ImageRequest,
    ) -> ImageResponse:
        """
        Generate an image.

        Parameters
        ----------
        request:
            Normalized image generation request.

        Returns
        -------
        ImageResponse
            Information about the generated image.
        """
        raise NotImplementedError
