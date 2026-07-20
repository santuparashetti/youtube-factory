import base64
import hashlib
import io
import json
import re
import time
from pathlib import Path

import httpx
from huggingface_hub import InferenceClient, hf_api
from loguru import logger
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from video_core.config.shared_settings import SharedSettings
from .base import VisionProvider, build_era_aware_prompt
from video_core.domain.visual_metadata import VisualMetadata
from video_core.visual_intelligence.prompt_package import PromptPackage
from .models import IssueSeverity, VisionIssue, VisionReviewResult

_RETRYABLE = (
    RuntimeError,
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
)

_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


class HuggingFaceQuotaError(Exception):
    """Raised when the Hugging Face API quota is exhausted (HTTP 429). Not retried."""


class HuggingFaceVisionProvider(VisionProvider):
    """Production-ready Hugging Face Inference API vision provider."""

    def __init__(self, settings: SharedSettings | None = None) -> None:
        self._settings = settings if settings is not None else SharedSettings()

        if not self._settings.hf_token:
            raise ValueError(
                "HF_TOKEN is not set. "
                "Add it to your .env file, or set VISION_REVIEW_PROVIDER to a different provider "
                "(e.g. VISION_REVIEW_PROVIDER=local). "
                "Make sure you run ytfactory from the repo root so .env is found."
            )
        if not self._settings.hf_vision_provider:
            raise ValueError(
                "HF_VISION_PROVIDER is not set. "
                "Add it to your .env file (e.g. HF_VISION_PROVIDER=hf-inference). "
                "Make sure you run ytfactory from the repo root so .env is found."
            )
        if not self._settings.hf_vision_model:
            raise ValueError(
                "HF_VISION_MODEL is not set. "
                "Add it to your .env file (e.g. HF_VISION_MODEL=Qwen/Qwen2.5-VL-7B-Instruct). "
                "Make sure you run ytfactory from the repo root so .env is found."
            )

        self._client: InferenceClient | None = None
        self._cache: dict[str, VisionReviewResult] = {}
        self._unhealthy_providers: set[str] = set()

        self._metrics = {
            "total_reviews": 0,
            "successful_reviews": 0,
            "failed_reviews": 0,
            "cache_hits": 0,
            "total_latency_ms": 0.0,
            "total_image_size_kb": 0.0,
            "total_score": 0.0,
            "provider_usage": {},
        }

    def _get_client(self) -> InferenceClient:
        if self._client is None:
            self._client = InferenceClient(
                provider=self._settings.hf_vision_provider,
                api_key=self._settings.hf_token,
            )
        return self._client

    def _optimize_image(self, image_path: Path) -> tuple[bytes, str]:
        """Read, optimize, and return image bytes and mime type."""
        suffix = image_path.suffix.lower()
        mime_type = _MIME_MAP.get(suffix)
        if mime_type is None:
            raise ValueError(
                f"Unsupported image format: {suffix}. Supported: png, jpg, jpeg, webp"
            )

        img = Image.open(image_path)

        if img.mode != "RGB":
            img = img.convert("RGB")

        max_side = 1024
        width, height = img.size
        if max(width, height) > max_side:
            scale = max_side / max(width, height)
            new_size = (int(width * scale), int(height * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        if suffix == ".png":
            img.save(buffer, format="PNG", optimize=True)
        else:
            img.save(buffer, format="JPEG", quality=90, optimize=True)

        return buffer.getvalue(), mime_type

    def _get_cache_key(self, image_bytes: bytes) -> str:
        return hashlib.sha256(
            image_bytes + self._settings.hf_vision_model.encode()
        ).hexdigest()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=5, max=30),
        reraise=True,
    )
    def _call_hf(self, prompt_text: str, data_uri: str) -> str:
        client = self._get_client()
        messages = [
            {
                "role": "system",
                "content": "You are an expert AI image quality reviewer.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt_text},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ]

        try:
            response = client.chat.completions.create(
                model=self._settings.hf_vision_model,
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
        except hf_api.HfHubHTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 429:
                raise HuggingFaceQuotaError(
                    f"Hugging Face quota exhausted ({exc}). "
                    "Wait before retrying or upgrade your plan."
                ) from exc
            if status_code in (401, 403, 404):
                self._unhealthy_providers.add(self._settings.hf_vision_provider)
                raise
            if status_code == 400 and "model" in str(exc).lower():
                self._unhealthy_providers.add(self._settings.hf_vision_provider)
                raise HuggingFaceQuotaError(
                    f"Model: {self._settings.hf_vision_model} is not supported by provider "
                    f"{self._settings.hf_vision_provider}. Original error: {exc}"
                ) from exc
            raise RuntimeError(f"Hugging Face API error: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(
                "Hugging Face request failed. The service may be temporarily unavailable."
            ) from exc

        return response.choices[0].message.content or ""

    def review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
        visual_metadata: VisualMetadata | None = None,
        prompt_package: PromptPackage | None = None,
    ) -> VisionReviewResult:
        if not image_path.exists():
            return VisionReviewResult.error_result(f"Image not found: {image_path}")

        try:
            return self._run_review(image_path, visual_prompt, scene_context, visual_metadata, prompt_package)
        except HuggingFaceQuotaError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Hugging Face vision review error for {}: {}", image_path.name, exc
            )
            return VisionReviewResult.error_result(
                f"Hugging Face vision review failed: {exc}"
            )

    def _run_review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
        visual_metadata: VisualMetadata | None = None,
        prompt_package: PromptPackage | None = None,
    ) -> VisionReviewResult:
        if self._settings.hf_vision_provider in self._unhealthy_providers:
            return VisionReviewResult.error_result(
                f"Provider {self._settings.hf_vision_provider} is marked unhealthy. "
                "Restart the application to reset health status."
            )

        try:
            image_bytes, mime_type = self._optimize_image(image_path)
        except Exception as exc:
            return VisionReviewResult.error_result(f"Image optimization failed: {exc}")

        image_size_kb = len(image_bytes) / 1024
        cache_key = self._get_cache_key(image_bytes)
        if cache_key in self._cache:
            self._metrics["cache_hits"] += 1
            logger.info(
                "Cache hit for {} (model={}, size={:.1f}KB)",
                image_path.name,
                self._settings.hf_vision_model,
                image_size_kb,
            )
            return self._cache[cache_key]

        prompt_text = self._build_prompt(visual_prompt, visual_metadata, prompt_package)
        b64 = base64.b64encode(image_bytes).decode()
        data_uri = f"data:{mime_type};base64,{b64}"

        img = Image.open(io.BytesIO(image_bytes))
        logger.info(
            "HF vision request: provider={}, model={}, image={}x{}, size={:.1f}KB, cache=miss",
            self._settings.hf_vision_provider,
            self._settings.hf_vision_model,
            img.width,
            img.height,
            image_size_kb,
        )

        start_time = time.perf_counter()
        raw_response = self._call_hf(prompt_text, data_uri)
        latency_ms = (time.perf_counter() - start_time) * 1000

        result = self._parse_response(raw_response)
        result.model_name = self._settings.hf_vision_model
        result.backend = "huggingface"
        result.raw_response = raw_response

        self._metrics["total_reviews"] += 1
        self._metrics["total_latency_ms"] += latency_ms
        self._metrics["total_image_size_kb"] += image_size_kb
        self._metrics["total_score"] += result.score
        provider_usage = self._metrics["provider_usage"].get(self._settings.hf_vision_provider, 0)
        self._metrics["provider_usage"][self._settings.hf_vision_provider] = provider_usage + 1

        if result.status == "ERROR":
            self._metrics["failed_reviews"] += 1
        else:
            self._metrics["successful_reviews"] += 1

        logger.info(
            "HF vision response: provider={}, model={}, status={}, score={}, confidence={}, issues={}, latency={:.0f}ms",
            self._settings.hf_vision_provider,
            self._settings.hf_vision_model,
            result.status,
            result.score,
            result.confidence,
            len(result.issues),
            latency_ms,
        )

        self._cache[cache_key] = result
        return result

    def _build_prompt(self, visual_prompt: str, visual_metadata: VisualMetadata | None = None, prompt_package: PromptPackage | None = None) -> str:
        return build_era_aware_prompt(visual_prompt, visual_metadata, prompt_package)

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
