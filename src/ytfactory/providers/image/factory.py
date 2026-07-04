from ytfactory.config.settings import Settings

from .base import ImageProvider
from .gemini import GeminiImageProvider
from .huggingface import HuggingFaceImageProvider
from .pollinations import PollinationsImageProvider


def get_image_provider(settings: Settings) -> ImageProvider:
    """Return configured image provider."""

    match settings.image_provider.lower():

        case "pollinations":
            return PollinationsImageProvider(settings)

        case "huggingface":
            return HuggingFaceImageProvider(settings)

        case "gemini":
            return GeminiImageProvider(settings)

        case _:
            raise ValueError(
                f"Unsupported image provider: {settings.image_provider}"
            )