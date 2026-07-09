"""Model Bootstrap — delegates model lifecycle to the Local AI Model Manager.

No download logic lives here. The LAMM is the single authority for all
local AI model operations: discovery, download, checksum, caching, backend
selection, self-healing, and manifest management.
"""

from __future__ import annotations

from pathlib import Path


from .models import CheckResult, CheckStatus


def bootstrap_models(base_dir: Path | None = None) -> list[CheckResult]:
    """Ensure all required models are ready. Idempotent.

    Uses the Local AI Model Manager to provision every enabled model.
    Models with auto_download=false are checked for presence only.
    Vision models are provisioned when image_review_enabled=true.
    """
    root = base_dir or Path.cwd()
    results: list[CheckResult] = []

    results.extend(_check_lamm_available())
    results.extend(_provision_via_lamm(root))

    return results


def _check_lamm_available() -> list[CheckResult]:
    """Verify the Local AI Model Manager package is importable."""
    try:
        from ytfactory.models import LocalAIModelManager  # noqa: F401

        return [
            CheckResult(
                name="model:lamm",
                status=CheckStatus.OK,
                message="Local AI Model Manager available",
            )
        ]
    except ImportError as exc:
        return [
            CheckResult(
                name="model:lamm",
                status=CheckStatus.WARNING,
                message="Local AI Model Manager import error",
                detail=str(exc),
            )
        ]


def _provision_via_lamm(root: Path) -> list[CheckResult]:
    """Provision all models through the LAMM and map results to CheckResult."""
    try:
        from ytfactory.models import LocalAIModelManager, ModelStatus
    except ImportError:
        return []

    # Determine if image review is enabled (affects vision model provisioning)
    image_review_enabled = _is_image_review_enabled()
    vision_model_name = _get_vision_model_name()

    manager = LocalAIModelManager(base_dir=root)
    results: list[CheckResult] = []

    for model_name, entry in manager._registry.items():
        if not entry.enabled:
            results.append(
                CheckResult(
                    name=f"model:{model_name}",
                    status=CheckStatus.SKIPPED,
                    message=f"Model '{model_name}' disabled in registry",
                )
            )
            continue

        # Vision model only provisioned when image review is enabled
        if model_name == vision_model_name and not image_review_enabled:
            results.append(
                CheckResult(
                    name=f"model:{model_name}",
                    status=CheckStatus.SKIPPED,
                    message=f"Vision model '{model_name}' skipped (image_review_enabled=false)",
                )
            )
            continue

        # Vision model: allow download when image_review_enabled=true (user opt-in)
        allow_dl: bool | None = True if (model_name == vision_model_name and image_review_enabled) else None
        provision = manager.provision(model_name, allow_download=allow_dl)

        if provision.skipped or provision.status == ModelStatus.SKIPPED:
            results.append(
                CheckResult(
                    name=f"model:{model_name}",
                    status=CheckStatus.SKIPPED,
                    message=provision.message,
                )
            )
        elif provision.ok:
            results.append(
                CheckResult(
                    name=f"model:{model_name}",
                    status=CheckStatus.OK,
                    message=f"Model '{model_name}' ready (backend: {provision.backend})",
                    detail=provision.message,
                )
            )
        elif provision.status == ModelStatus.MISSING:
            # Missing with auto_download=false is a warning, not an error
            results.append(
                CheckResult(
                    name=f"model:{model_name}",
                    status=CheckStatus.WARNING,
                    message=f"Model '{model_name}' not downloaded yet",
                    detail=provision.message,
                )
            )
        else:
            results.append(
                CheckResult(
                    name=f"model:{model_name}",
                    status=CheckStatus.ERROR,
                    message=f"Model '{model_name}' provisioning failed",
                    detail=provision.error or provision.message,
                )
            )

    return results


def _is_image_review_enabled() -> bool:
    """Check whether image_review_enabled is set in the environment."""
    try:
        from ytfactory.config.settings import Settings

        return Settings().image_review_enabled
    except Exception:
        return False


def _get_vision_model_name() -> str:
    """Return the configured vision model registry key."""
    try:
        from ytfactory.config.settings import Settings

        return Settings().vision_review_local_model
    except Exception:
        return "minicpm_v2_6"
