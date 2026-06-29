from pathlib import Path
import base64

from google import genai
from google.genai import types

from ytfactory.config.settings import Settings
from ytfactory.domain.image import (
    ImageRequest,
    ImageResponse,
)
from ytfactory.providers.image.base import ImageProvider


class GeminiImageProvider(ImageProvider):
    """Gemini Image Generation provider."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
        )

    def generate(
        self,
        request: ImageRequest,
    ) -> ImageResponse:
        response = self._client.models.generate_content(
            model="gemini-2.5-flash-image-preview",
            contents=request.prompt,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )

        request.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        image_written = False

        for candidate in response.candidates:
            if not candidate.content:
                continue

            for part in candidate.content.parts:
                if getattr(part, "inline_data", None):
                    image = base64.b64decode(part.inline_data.data)

                    request.output_path.write_bytes(image)

                    image_written = True
                    break

            if image_written:
                break

        if not image_written:
            raise RuntimeError(
                "Gemini did not return an image."
            )

        return ImageResponse(
            file=request.output_path,
            provider="gemini_image",
            width=request.width,
            height=request.height,
        )