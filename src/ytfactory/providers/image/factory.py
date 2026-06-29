from ytfactory.config.settings import Settings
from ytfactory.providers.image.base import ImageProvider
from ytfactory.providers.image.gemini import GeminiImageProvider


def get_image_provider(settings: Settings) -> ImageProvider:
    """Return configured image provider."""

    match settings.image_provider.lower():
        case "gemini_image":
            return GeminiImageProvider(settings)

        case _:
            raise ValueError(
                f"Unsupported image provider: {settings.image_provider}"
            )