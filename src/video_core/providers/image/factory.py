from video_core.config.shared_settings import SharedSettings

from .base import ImageProvider
from .gemini import GeminiImageProvider
from .huggingface import HuggingFaceImageProvider
from .pollinations import PollinationsImageProvider


def get_image_provider(settings: SharedSettings) -> ImageProvider:
    """Return configured image provider."""

    match settings.image_provider.lower():
        case "pollinations":
            return PollinationsImageProvider(settings)

        case "huggingface":
            return HuggingFaceImageProvider(settings)

        case "gemini":
            return GeminiImageProvider(settings)

        case "a1111" | "automatic1111" | "sd-webui":
            from .a1111 import A1111ImageProvider

            return A1111ImageProvider(settings)

        case _:
            raise ValueError(
                f"Unsupported image provider: {settings.image_provider}. "
                "Valid options: pollinations, huggingface, gemini, a1111"
            )
