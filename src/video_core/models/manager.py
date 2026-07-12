"""Local AI Model Manager — single authority for all local model lifecycle.

No feature pipeline may download or manage local models directly.
All model lifecycle operations route through this manager.

Responsibilities
----------------
- Discover required models from the registry
- Download missing models (HuggingFace hub)
- Resume interrupted downloads (hub handles this transparently)
- Verify model integrity (package availability + cache presence)
- Select compute backend (CUDA → MPS → CPU)
- Detect corrupted models and trigger re-download
- Update the model manifest
- Generate diagnostic reports
- Validate capability contracts before marking models READY
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from loguru import logger

from .backend import Backend, describe_backend, select_backend
from .bundle import BundleProvisioner
from .capabilities import validate_capabilities
from .manifest import get_state, load_manifest, update_state
from .models import (
    FailureReason,
    ModelBundle,
    ModelEntry,
    ModelState,
    ModelStatus,
    ProvisionResult,
)
from .registry import load_registry


class LocalAIModelManager:
    """Manages the full lifecycle of all local AI models.

    Usage (typical)
    ---------------
        manager = LocalAIModelManager(base_dir=Path.cwd())
        result = manager.provision("minicpm_v2_6")
        if result.ok:
            backend = result.backend
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        registry_path: Path | None = None,
    ) -> None:
        self._base_dir = base_dir or Path.cwd()
        self._registry = load_registry(registry_path)
        self._bundle_provisioner = BundleProvisioner(self._base_dir)

    # ── Public API ────────────────────────────────────────────────────────

    def provision(
        self,
        model_name: str,
        *,
        force: bool = False,
        allow_download: bool | None = None,
    ) -> ProvisionResult:
        """Ensure *model_name* is available, downloading if permitted.

        Parameters
        ----------
        model_name:
            Registry key (e.g. ``"minicpm_v2_6"``).
        force:
            Re-download even if already present.
        allow_download:
            Override the registry ``auto_download`` flag.  When ``None``
            (default) the registry value is used.
        """
        entry = self._registry.get(model_name)
        if entry is None:
            return ProvisionResult(
                name=model_name,
                status=ModelStatus.ERROR,
                message=f"Model '{model_name}' not found in registry",
                error="not_in_registry",
            )

        if not entry.enabled:
            return ProvisionResult(
                name=model_name,
                status=ModelStatus.SKIPPED,
                message=f"Model '{model_name}' disabled in registry",
                skipped=True,
            )

        # Check required packages
        missing_pkgs = self._missing_packages(entry)
        if missing_pkgs:
            msg = f"Required packages missing: {', '.join(missing_pkgs)}"
            state = ModelState(
                name=model_name,
                status=ModelStatus.MISSING,
                error=msg,
                packages_ok=False,
                capabilities=list(entry.capabilities),
            )
            update_state(self._base_dir, state)
            return ProvisionResult(
                name=model_name,
                status=ModelStatus.MISSING,
                message=msg,
                error=msg,
                capabilities=list(entry.capabilities),
            )

        # Check existing manifest state
        existing = get_state(self._base_dir, model_name)
        if (
            not force
            and existing is not None
            and existing.status == ModelStatus.VERIFIED
        ):
            logger.debug("Model '{}' already verified (backend: {})", model_name, existing.backend)
            return ProvisionResult(
                name=model_name,
                status=ModelStatus.VERIFIED,
                backend=existing.backend,
                message="Already verified",
                capabilities=existing.capabilities,
                bundle_artifacts=existing.bundle_artifacts,
                checksum_verified=existing.checksum_verified,
            )

        # Select backend
        backend = select_backend(entry.backends)

        # Decide whether to download
        should_download = allow_download if allow_download is not None else entry.auto_download
        has_repo = bool(entry.hf_repo)

        if has_repo and (should_download or force):
            return self._download_and_verify(entry, backend, force=force)

        # No download — verify presence from HF cache (or lazy-model quick-pass)
        return self._verify_from_cache(entry, backend)

    def provision_all(
        self,
        *,
        required_only: bool = False,
        allow_download: bool | None = None,
    ) -> list[ProvisionResult]:
        """Provision all enabled models from the registry."""
        results: list[ProvisionResult] = []
        for name, entry in self._registry.items():
            if not entry.enabled:
                continue
            if required_only and not entry.required:
                continue
            results.append(self.provision(name, allow_download=allow_download))
        return results

    def validate_capabilities(
        self,
        model_name: str,
        required: list[str],
    ) -> list[str]:
        """Validate that *model_name* declares all *required* capabilities.

        Returns a list of missing capability names (empty → all satisfied).
        Callers should treat a non-empty return as a pre-condition failure
        before loading the model.

        Example
        -------
            missing = manager.validate_capabilities("minicpm_v2_6", ["image_review"])
            if missing:
                raise RuntimeError(capability_error_message("minicpm_v2_6", missing))
        """
        entry = self._registry.get(model_name)
        declared = entry.capabilities if entry is not None else []
        return validate_capabilities(declared, required)

    def get_bundle(self, model_name: str) -> ModelBundle | None:
        """Return the ModelBundle for *model_name*, or None if not in registry."""
        entry = self._registry.get(model_name)
        return entry.bundle if entry is not None else None

    def status(self, model_name: str) -> ModelState:
        """Return current manifest state for *model_name*."""
        state = get_state(self._base_dir, model_name)
        return state or ModelState(name=model_name, status=ModelStatus.UNKNOWN)

    def status_all(self) -> dict[str, ModelState]:
        """Return manifest state for all known models."""
        return load_manifest(self._base_dir)

    def heal(self, model_name: str) -> ProvisionResult:
        """Detect and repair a corrupted model by re-downloading."""
        return self.provision(model_name, force=True, allow_download=True)

    def get_backend(self, model_name: str) -> Backend:
        """Return the backend for a provisioned model (CPU if unknown)."""
        state = get_state(self._base_dir, model_name)
        if state and state.backend:
            try:
                return Backend(state.backend)
            except ValueError:
                pass
        entry = self._registry.get(model_name)
        backends = entry.backends if entry else None
        return select_backend(backends)

    def diagnostics(self) -> list[dict]:
        """Generate a diagnostic report for all registry entries."""
        report: list[dict] = []
        manifest = load_manifest(self._base_dir)
        for name, entry in self._registry.items():
            state = manifest.get(name)
            missing_pkgs = self._missing_packages(entry)
            report.append({
                "name": name,
                "description": entry.description,
                "enabled": entry.enabled,
                "required": entry.required,
                "status": state.status.value if state else ModelStatus.UNKNOWN.value,
                "backend": state.backend if state else "",
                "packages_ok": not missing_pkgs,
                "missing_packages": missing_pkgs,
                "hf_repo": entry.hf_repo,
                "runtime": entry.runtime.value,
                "capabilities": list(entry.capabilities),
                "checksum_verified": state.checksum_verified if state else False,
            })
        return report

    # ── Internal helpers ──────────────────────────────────────────────────

    def _download_and_verify(
        self,
        entry: ModelEntry,
        backend: Backend,
        *,
        force: bool = False,
    ) -> ProvisionResult:
        """Download model via BundleProvisioner and mark as verified."""
        bundle = entry.bundle
        if bundle is None:
            # Fallback: legacy path (no bundle section ever parsed)
            return self._legacy_download(entry, backend, force=force)

        logger.info(
            "Provisioning model '{}' from {} via {} (backend: {})",
            entry.name, entry.hf_repo, entry.runtime.value, describe_backend(backend),
        )

        state = ModelState(
            name=entry.name,
            status=ModelStatus.DOWNLOADING,
            backend=backend.value,
            capabilities=list(entry.capabilities),
        )
        update_state(self._base_dir, state)

        status, message, artifact_paths, checksum_verified = self._bundle_provisioner.provision(
            entry.name,
            bundle,
            entry.hf_repo,
            entry.revision,
            force=force,
        )

        failure_reason = ""
        if status in (ModelStatus.ERROR, ModelStatus.CORRUPTED):
            # Extract FailureReason prefix from message if present
            for reason in FailureReason:
                if message.startswith(reason.value):
                    failure_reason = reason.value
                    break
            if not failure_reason:
                failure_reason = FailureReason.DOWNLOAD_FAILED.value

        final_state = ModelState(
            name=entry.name,
            status=status,
            backend=backend.value,
            cache_path=list(artifact_paths.values())[0] if artifact_paths else "",
            packages_ok=status == ModelStatus.VERIFIED,
            capabilities=list(entry.capabilities),
            checksum_verified=checksum_verified,
            bundle_artifacts=artifact_paths,
            failure_reason=failure_reason,
        )
        update_state(self._base_dir, final_state)

        if status == ModelStatus.VERIFIED:
            logger.info("Model '{}' provisioned: {}", entry.name, message)
        else:
            logger.error("Model '{}' provisioning failed: {}", entry.name, message)

        return ProvisionResult(
            name=entry.name,
            status=status,
            backend=backend.value if status == ModelStatus.VERIFIED else "cpu",
            message=message,
            error=message if status != ModelStatus.VERIFIED else "",
            failure_reason=failure_reason,
            capabilities=list(entry.capabilities),
            bundle_artifacts=artifact_paths,
            checksum_verified=checksum_verified,
        )

    def _legacy_download(
        self,
        entry: ModelEntry,
        backend: Backend,
        *,
        force: bool = False,
    ) -> ProvisionResult:
        """Legacy snapshot_download path when bundle section is absent."""
        try:
            from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
        except ImportError:
            msg = "huggingface_hub not installed — run: uv pip install huggingface-hub"
            return ProvisionResult(
                name=entry.name,
                status=ModelStatus.ERROR,
                message=msg,
                error=msg,
            )

        logger.info(
            "Downloading model '{}' from {} (backend: {})",
            entry.name, entry.hf_repo, describe_backend(backend),
        )
        try:
            state = ModelState(name=entry.name, status=ModelStatus.DOWNLOADING, backend=backend.value)
            update_state(self._base_dir, state)

            cache_path = snapshot_download(
                repo_id=entry.hf_repo,
                revision=entry.revision,
                ignore_patterns=["*.msgpack", "flax_model*"],
            )
            state = ModelState(
                name=entry.name,
                status=ModelStatus.VERIFIED,
                backend=backend.value,
                cache_path=str(cache_path),
                packages_ok=True,
            )
            update_state(self._base_dir, state)
            logger.info("Model '{}' downloaded and verified at {}", entry.name, cache_path)
            return ProvisionResult(
                name=entry.name,
                status=ModelStatus.VERIFIED,
                backend=backend.value,
                message=f"Downloaded to {cache_path}",
            )
        except Exception as exc:
            err = str(exc)
            state = ModelState(
                name=entry.name,
                status=ModelStatus.ERROR,
                backend=backend.value,
                error=err,
            )
            update_state(self._base_dir, state)
            logger.error("Failed to download model '{}': {}", entry.name, err)
            return ProvisionResult(
                name=entry.name,
                status=ModelStatus.ERROR,
                message=f"Download failed: {err}",
                error=err,
            )

    def _verify_from_cache(self, entry: ModelEntry, backend: Backend) -> ProvisionResult:
        """Check if model is present in HuggingFace cache without downloading."""
        if not entry.hf_repo:
            # Lazy models (whisperx, silero_vad) — just verify packages
            state = ModelState(
                name=entry.name,
                status=ModelStatus.VERIFIED,
                backend=backend.value,
                packages_ok=True,
                capabilities=list(entry.capabilities),
            )
            update_state(self._base_dir, state)
            return ProvisionResult(
                name=entry.name,
                status=ModelStatus.VERIFIED,
                backend=backend.value,
                message="Lazy model — downloads on first use",
                capabilities=list(entry.capabilities),
            )

        # Try to find in HF cache
        try:
            from huggingface_hub import try_to_load_from_cache  # type: ignore[import-not-found]
            result = try_to_load_from_cache(entry.hf_repo, "config.json")
            if result and result != "not in cache":
                cache_path = str(Path(result).parent)
                state = ModelState(
                    name=entry.name,
                    status=ModelStatus.VERIFIED,
                    backend=backend.value,
                    cache_path=cache_path,
                    packages_ok=True,
                    capabilities=list(entry.capabilities),
                )
                update_state(self._base_dir, state)
                return ProvisionResult(
                    name=entry.name,
                    status=ModelStatus.VERIFIED,
                    backend=backend.value,
                    message="Found in HuggingFace cache",
                    capabilities=list(entry.capabilities),
                )
        except Exception:
            pass

        # Not in cache and auto_download=false
        msg = f"Model '{entry.name}' not in cache (auto_download=false). Enable image_review_enabled=true to trigger download."
        state = ModelState(
            name=entry.name,
            status=ModelStatus.MISSING,
            backend=backend.value,
            error=msg,
            capabilities=list(entry.capabilities),
        )
        update_state(self._base_dir, state)
        return ProvisionResult(
            name=entry.name,
            status=ModelStatus.MISSING,
            message=msg,
            capabilities=list(entry.capabilities),
        )

    @staticmethod
    def _missing_packages(entry: ModelEntry) -> list[str]:
        missing: list[str] = []
        for pkg in entry.requires_packages:
            if importlib.util.find_spec(pkg) is None:
                missing.append(pkg)
        return missing
