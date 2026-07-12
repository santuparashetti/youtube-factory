"""Local AI Model Manager — single authority for all local AI model lifecycle."""

from .manager import LocalAIModelManager
from .models import (
    Backend,
    BundleArtifact,
    BundleRuntime,
    FailureReason,
    ModelBundle,
    ModelEntry,
    ModelState,
    ModelStatus,
    ProvisionResult,
    WarmInferenceConfig,
)
from .registry import load_registry

__all__ = [
    "LocalAIModelManager",
    "Backend",
    "BundleArtifact",
    "BundleRuntime",
    "FailureReason",
    "ModelBundle",
    "ModelEntry",
    "ModelState",
    "ModelStatus",
    "ProvisionResult",
    "WarmInferenceConfig",
    "load_registry",
]
