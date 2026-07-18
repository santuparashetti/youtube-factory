"""llama.cpp vision provider — runs GGUF multimodal models via llama-cpp-python.

All model-specific behaviour is read from the LAMM registry:
- ``text_model`` bundle artifact  → main GGUF weights path
- ``vision_projector`` artifact   → mmproj GGUF path (if present)
- ``bundle.chat_format``          → llama-cpp-python chat format string

No model names, chat format strings, or projector filenames are hardcoded here.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import re
from pathlib import Path

from loguru import logger

from video_core.models import LocalAIModelManager, ModelStatus
from video_core.models.backend import Backend, select_backend

from .base import HAND_ANATOMY_PROMPT, VISION_REVIEW_PROMPT, VisionProvider, is_hand_focal
from .models import IssueSeverity, VisionIssue, VisionReviewResult


@contextlib.contextmanager
def _silence_c_output():
    """Redirect C-level fd 1/2 to /dev/null to suppress llama.cpp's internal logs.

    ``verbose=False`` suppresses Python-level output but the C library writes
    ``load_tensors:``, ``tokenize:``, ``add_text:`` etc. directly to the OS
    file descriptors and cannot be filtered by Python's logging system.
    """
    null_fd = os.open(os.devnull, os.O_WRONLY)
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
        yield
    finally:
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        os.close(null_fd)
        os.close(saved_out)
        os.close(saved_err)


class LlamaCppVisionProvider(VisionProvider):
    """Vision provider backed by a llama-cpp-python GGUF bundle.

    The loaded ``Llama`` instance is created lazily on the first ``review()``
    call so that bootstrap can succeed even before the GGUF files are present.

    Parameters
    ----------
    model_name:
        Registry key (e.g. ``"qwen2_5_vl_3b"``).
    base_dir:
        Repo root — passed to the LAMM for manifest management.
    """

    def __init__(
        self,
        model_name: str,
        base_dir: Path | None = None,
    ) -> None:
        self._model_name = model_name
        self._manager = LocalAIModelManager(base_dir)
        self._model: object | None = None

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
            logger.warning(
                "llama.cpp vision review error for {}: {}", image_path.name, exc
            )
            return VisionReviewResult.error_result(str(exc))

    # ── Internal ───────────────────────────────────────────────────────────

    def _run_review(
        self,
        image_path: Path,
        visual_prompt: str,
        scene_context: dict | None = None,
    ) -> VisionReviewResult:
        model = self._load_model()
        if model is None:
            return VisionReviewResult.skipped(
                f"llama.cpp model '{self._model_name}' not available — "
                "install llama-cpp-python or run ytfactory setup"
            )

        prompt = self._build_prompt(visual_prompt)
        try:
            response = self._infer(model, image_path, prompt)
        except Exception as exc:
            return VisionReviewResult.error_result(f"Inference failed: {exc}")

        result = self._parse_response(response)
        entry = self._manager._registry.get(self._model_name)
        result.model_name = self._model_name
        result.backend = select_backend(entry.backends if entry else None).value
        result.raw_response = response
        return result

    def _load_model(self) -> object | None:
        if self._model is not None:
            return self._model

        try:
            from llama_cpp import Llama  # type: ignore[import-not-found]
        except ImportError:
            logger.debug(
                "llama-cpp-python not installed — llama.cpp vision provider unavailable"
            )
            return None

        # Capability check before loading
        missing_caps = self._manager.validate_capabilities(
            self._model_name, ["image_review"]
        )
        if missing_caps:
            logger.warning(
                "Model '{}' missing required capabilities: {} — skipping",
                self._model_name,
                ", ".join(f"MISSING_CAPABILITY({c})" for c in missing_caps),
            )
            return None

        # Provision via LAMM (auto_download from registry controls whether to download)
        result = self._manager.provision(self._model_name)
        if result.status not in (ModelStatus.VERIFIED, ModelStatus.DOWNLOADED):
            logger.debug(
                "Model '{}' not ready (status={}): {}",
                self._model_name,
                result.status,
                result.message,
            )
            return None

        text_model_path = result.bundle_artifacts.get("text_model")
        projector_path = result.bundle_artifacts.get("vision_projector")

        if not text_model_path:
            logger.error(
                "Model '{}': 'text_model' artifact path missing from bundle", self._model_name
            )
            return None

        entry = self._manager._registry.get(self._model_name)
        chat_format: str | None = (
            entry.bundle.chat_format
            if entry and entry.bundle and entry.bundle.chat_format
            else None
        )
        backend = select_backend(entry.backends if entry else None)
        n_gpu_layers = -1 if backend == Backend.CUDA else 0

        try:
            load_kwargs: dict[str, object] = {  # type: ignore[type-arg]
                "model_path": text_model_path,
                "n_ctx": 16384,
                "n_batch": 4096,
                "n_ubatch": 4096,
                "n_gpu_layers": n_gpu_layers,
                "verbose": False,
            }

            # Resolve the chat handler class by name from the registry bundle's
            # chat_format field (e.g. "Qwen25VLChatHandler").  Nothing is hardcoded.
            if chat_format and projector_path:
                try:
                    import llama_cpp.llama_chat_format as _fmt  # type: ignore[import-not-found]
                    handler_cls = getattr(_fmt, chat_format)
                    load_kwargs["chat_handler"] = handler_cls(
                        clip_model_path=projector_path, verbose=False
                    )
                    logger.debug(
                        "llama.cpp: resolved chat handler '{}' for '{}'",
                        chat_format,
                        self._model_name,
                    )
                except AttributeError:
                    logger.warning(
                        "Chat handler '{}' not found in llama_cpp.llama_chat_format — "
                        "falling back to no handler",
                        chat_format,
                    )

            logger.info(
                "Loading llama.cpp model '{}' on {} (handler={})",
                self._model_name,
                backend.value,
                chat_format or "none",
            )
            with _silence_c_output():
                self._model = Llama(**load_kwargs)  # type: ignore[arg-type]
            logger.info("llama.cpp model '{}' loaded", self._model_name)
            return self._model

        except Exception as exc:
            logger.error(
                "Failed to load llama.cpp model '{}': {}", self._model_name, exc
            )
            return None

    def _build_prompt(self, visual_prompt: str) -> str:
        hand_block = HAND_ANATOMY_PROMPT if is_hand_focal(visual_prompt) else ""
        return (
            f"{VISION_REVIEW_PROMPT}{hand_block}\n\n"
            f"The image was generated with this prompt:\n{visual_prompt}\n\n"
            "Review the image against all criteria above and return your JSON assessment."
        )

    def _infer(self, model: object, image_path: Path, prompt: str) -> str:
        suffix = image_path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        data_uri = f"data:{mime};base64,{b64}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        with _silence_c_output():
            response = model.create_chat_completion(  # type: ignore[union-attr, attr-defined]
                messages=messages,
                max_tokens=512,
                temperature=0.1,
            )
        return str(response["choices"][0]["message"]["content"])

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
