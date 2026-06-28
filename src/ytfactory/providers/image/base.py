from abc import ABC, abstractmethod
from pathlib import Path


class ImageProvider(ABC):
    """Base interface for all image providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        output_path: Path,
        *,
        width: int = 1280,
        height: int = 720,
    ) -> Path:
        """
        Generate an image.

        Parameters
        ----------
        prompt:
            Prompt describing the image.

        output_path:
            Destination PNG path.

        width:
            Output width.

        height:
            Output height.

        Returns
        -------
        Path
            Generated image path.
        """
        raise NotImplementedError