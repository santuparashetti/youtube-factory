"""Local vision provider — runs a local vision model via the LAMM.

Currently supports:
  - minicpm_v2_6 (openbmb/MiniCPM-V-2_6)

Future models are switchable through configuration only.
The pipeline never contains model-specific logic — all dispatching
is handled inside this provider.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger

from ytfactory.models import LocalAIModelManager, ModelStatus
from ytfactory.models.backend import Backend, select_backend

from .base import VISION_REVIEW_PROMPT, VisionProvider
from .models import IssueSeverity, VisionIssue, VisionReviewResult


class LocalVisionProvider(VisionProvider):
    """Run a configured local vision model for image review.

    The model is loaded lazily on the first ``review()`` call so that
    bootstrap can succeed even when the model is not yet downloaded.

    Parameters
    ----------
    model_name:
        Registry key (e.g. ``"minicpm_v2_6"``).
    base_dir:
        Repo root — passed to the LAMM for manifest management.
    """

    def __init__(
        self,
        model_name: str = "minicpm_v2_6",
        base_dir: Path | None = None,
    ) -> None:
        self._model_name = model_name
        self._manager = LocalAIModelManager(base_dir)
        self._model: object | None = None
        self._tokenizer: object | None = None
        self._backend: Backend | None = None

    # ── VisionProvider interface ───────────────────────────────────────────

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
        except Exception as exc:  # noqa: BLE001
            logger.warning("Vision review error for {}: {}", image_path.name, exc)
            return VisionReviewResult.error_result(str(exc))

    # ── Internal ───────────────────────────────────────────────────────────

    def _run_review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
    ) -> VisionReviewResult:
        model, tokenizer, backend = self._load_model()
        if model is None:
            return VisionReviewResult.skipped(
                f"Local model '{self._model_name}' not available — install torch+transformers or use image_review_enabled=false"
            )

        prompt = self._build_prompt(visual_prompt)

        try:
            response = self._infer(model, tokenizer, image_path, prompt, backend)
        except Exception as exc:
            return VisionReviewResult.error_result(f"Inference failed: {exc}")

        result = self._parse_response(response)
        result.model_name = self._model_name
        result.backend = backend.value
        result.raw_response = response
        return result

    def _load_model(self) -> tuple[object | None, object | None, Backend]:
        if self._model is not None:
            return self._model, self._tokenizer, self._backend or Backend.CPU

        # Check packages
        try:
            import torch  # type: ignore[import-not-found]  # noqa: F401
            from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found]
        except ImportError:
            logger.debug(
                "torch/transformers not installed — local vision provider unavailable"
            )
            return None, None, Backend.CPU

        # Capability contract: ensure model declares image_review before loading
        missing_caps = self._manager.validate_capabilities(
            self._model_name, ["image_review"]
        )
        if missing_caps:
            logger.warning(
                "Model '{}' missing required capabilities: {} — skipping local vision review",
                self._model_name,
                ", ".join(f"MISSING_CAPABILITY({c})" for c in missing_caps),
            )
            return None, None, Backend.CPU

        # Provision via LAMM
        result = self._manager.provision(self._model_name)
        if result.status not in (ModelStatus.VERIFIED, ModelStatus.DOWNLOADED):
            logger.debug(
                "Model '{}' not ready (status={}): {}",
                self._model_name,
                result.status,
                result.message,
            )
            return None, None, Backend.CPU

        backend = select_backend(self._get_entry_backends())

        try:
            import torch  # type: ignore[import-not-found]
            from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found]

            hf_repo = self._manager._registry[self._model_name].hf_repo
            logger.info(
                "Loading local vision model '{}' on {}", self._model_name, backend.value
            )

            dtype = torch.bfloat16 if backend != Backend.CPU else torch.float32

            tokenizer = AutoTokenizer.from_pretrained(hf_repo, trust_remote_code=True)
            model = AutoModel.from_pretrained(
                hf_repo,
                trust_remote_code=True,
                torch_dtype=dtype,
                low_cpu_mem_usage=True,
            )

            device = (
                "cuda"
                if backend == Backend.CUDA
                else ("mps" if backend == Backend.MPS else "cpu")
            )
            model = model.to(device).eval()  # type: ignore[union-attr]

            self._model = model
            self._tokenizer = tokenizer
            self._backend = backend
            logger.info(
                "Local vision model '{}' loaded on {}", self._model_name, device
            )
            return model, tokenizer, backend

        except Exception as exc:
            logger.error("Failed to load local model '{}': {}", self._model_name, exc)
            return None, None, Backend.CPU

    def _get_entry_backends(self) -> list[str]:
        entry = self._manager._registry.get(self._model_name)
        return entry.backends if entry else ["cuda", "mps", "cpu"]

    def _build_prompt(self, visual_prompt: str) -> str:
        return (
            f"{VISION_REVIEW_PROMPT}\n\n"
            f"The image was generated with this prompt:\n{visual_prompt}\n\n"
            "Review the image against all criteria above and return your JSON assessment."
        )

    def _infer(
        self,
        model: object,
        tokenizer: object,
        image_path: Path,
        prompt: str,
        backend: Backend,
    ) -> str:
        from PIL import Image  # type: ignore[import-not-found]

        image = Image.open(image_path).convert("RGB")

        msgs = [{"role": "user", "content": [image, prompt]}]

        # MiniCPM-V 2.6 chat API
        response = model.chat(  # type: ignore[union-attr, attr-defined]
            image=None,
            msgs=msgs,
            tokenizer=tokenizer,
        )
        return str(response)

    def _parse_response(self, raw: str) -> VisionReviewResult:
        """Parse the model's JSON response into a VisionReviewResult."""
        # Strip markdown fences
        cleaned = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        cleaned = cleaned.rstrip("```").strip()

        # Find JSON object
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
