"""Vision provider factory — dispatches on settings."""

from __future__ import annotations

from pathlib import Path

from .base import VisionProvider


def get_vision_provider(
    provider_name: str,
    local_model: str = "minicpm_v2_6",
    base_dir: Path | None = None,
) -> VisionProvider:
    """Return configured vision provider.

    Parameters
    ----------
    provider_name:
        ``"local"`` or ``"mock"``.
    local_model:
        Registry key for the local model (only used when provider_name="local").
    base_dir:
        Repo root — passed to the LAMM when using local provider.
    """
    match provider_name.lower():
        case "mock":
            from .mock import MockVisionProvider

            return MockVisionProvider()

        case "local":
            from video_core.models import LocalAIModelManager
            from video_core.models.models import BundleRuntime

            manager = LocalAIModelManager(base_dir)
            entry = manager._registry.get(local_model)
            runtime = entry.runtime if entry is not None else BundleRuntime.TRANSFORMERS

            if runtime == BundleRuntime.LLAMA_CPP:
                from .llama_cpp_provider import LlamaCppVisionProvider

                return LlamaCppVisionProvider(model_name=local_model, base_dir=base_dir)

            from .local import LocalVisionProvider

            return LocalVisionProvider(model_name=local_model, base_dir=base_dir)

        case _:
            raise ValueError(
                f"Unsupported vision provider: '{provider_name}'. "
                "Valid options: local, mock"
            )
