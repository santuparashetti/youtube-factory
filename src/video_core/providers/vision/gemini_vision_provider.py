import json
import re
from pathlib import Path

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from video_core.config.shared_settings import SharedSettings
from .base import HAND_ANATOMY_PROMPT, VISION_REVIEW_PROMPT, VisionProvider, is_hand_focal
from .models import IssueSeverity, VisionIssue, VisionReviewResult

_RETRYABLE = (
    RuntimeError,
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpx.ConnectError,
)

_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class GeminiQuotaError(Exception):
    """Raised when the Gemini API daily quota is exhausted (HTTP 429). Not retried."""


class GeminiVisionProvider(VisionProvider):
    """Google Gemini multimodal vision provider for image QA."""

    def __init__(self, settings: SharedSettings | None = None) -> None:
        self._settings = settings if settings is not None else SharedSettings()
        if not self._settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file, or set VISION_REVIEW_PROVIDER to a different provider "
                "(e.g. VISION_REVIEW_PROVIDER=local). "
                "Make sure you run ytfactory from the repo root so .env is found."
            )
        self._client = genai.Client(api_key=self._settings.gemini_api_key)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        reraise=True,
    )
    def _call_gemini(self, prompt_text: str, image_bytes: bytes, mime_type: str) -> str:
        model = getattr(self._settings, "gemini_vision_model", None) or self._settings.gemini_text_model
        logger.info("Using Gemini vision model: {}", model)

        try:
            response = self._client.models.generate_content(
                model=model,
                contents=[
                    prompt_text,
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
        except genai_errors.ClientError as exc:
            if getattr(exc, "code", None) == 429:
                raise GeminiQuotaError(
                    f"Gemini daily quota exhausted ({exc}). "
                    "Upgrade to a paid tier or wait until tomorrow."
                ) from exc
            raise RuntimeError(f"Gemini API error: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(
                "Gemini request failed. The service may be temporarily unavailable."
            ) from exc

        return response.text or ""

    def review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
    ) -> VisionReviewResult:
        if not image_path.exists():
            return VisionReviewResult.error_result(f"Image not found: {image_path}")

        try:
            return self._run_review(image_path, visual_prompt, scene_context)
        except GeminiQuotaError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gemini vision review error for {}: {}", image_path.name, exc)
            return VisionReviewResult.error_result(f"Gemini vision review failed: {exc}")

    def _run_review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
    ) -> VisionReviewResult:
        prompt_text = self._build_prompt(visual_prompt)
        image_bytes = image_path.read_bytes()
        suffix = image_path.suffix.lower()
        mime_type = _MIME_MAP.get(suffix)
        if mime_type is None:
            return VisionReviewResult.error_result(
                f"Unsupported image format: {suffix}. Supported: png, jpg, jpeg, webp"
            )

        raw_response = self._call_gemini(prompt_text, image_bytes, mime_type)
        result = self._parse_response(raw_response)
        result.model_name = (
            getattr(self._settings, "gemini_vision_model", None)
            or self._settings.gemini_text_model
        )
        result.backend = "gemini"
        result.raw_response = raw_response
        return result

    def _build_prompt(self, visual_prompt: str) -> str:
        hand_block = HAND_ANATOMY_PROMPT if is_hand_focal(visual_prompt) else ""
        return (
            f"{VISION_REVIEW_PROMPT}{hand_block}\n\n"
            f"The image was generated with this prompt:\n{visual_prompt}\n\n"
            "Review the image against all criteria above and return your JSON assessment."
        )

    def _parse_response(self, raw: str) -> VisionReviewResult:
        cleaned = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        cleaned = cleaned.rstrip("```").strip()

        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return VisionReviewResult.error_result(f"No JSON in response: {raw[:200]}")

        try:
            data = json.loads(match.group())
        except json.JSONDecodeError as exc:
            return VisionReviewResult.error_result(
                f"JSON parse error: {exc} — {raw[:200]}"
            )

        issues: list[VisionIssue] = []
        for item in data.get("issues") or []:
            try:
                severity = IssueSeverity(item.get("severity", "MEDIUM"))
            except ValueError:
                severity = IssueSeverity.MEDIUM
            issues.append(
                VisionIssue(
                    category=str(item.get("category", "unknown")),
                    description=str(item.get("description", "")),
                    severity=severity,
                    location=str(item.get("location", "")),
                )
            )

        status = str(data.get("status", "FAIL")).upper()
        if status not in ("PASS", "FAIL", "SKIP", "ERROR"):
            status = "FAIL"

        return VisionReviewResult(
            status=status,
            score=float(data.get("score", 0)),
            confidence=float(data.get("confidence", 0)),
            issues=issues,
            recommend_regeneration=bool(data.get("recommend_regeneration", True)),
        )
