"""BootstrapEngine — main orchestrator for the idempotent first-run setup."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from .config_validator import migrate_config, validate_config
from .env_checker import check_environment
from .healer import heal
from .model_bootstrap import bootstrap_models
from .models import BootstrapResult, CheckResult, CheckStatus
from .provider_validator import validate_providers
from .report import write_environment_report
from .version_manager import (
    build_manifest,
    is_manifest_current,
    load_manifest,
    save_manifest,
)
from .workspace import bootstrap_workspace


class BootstrapEngine:
    """Orchestrates the full first-run bootstrap sequence.

    All phases are idempotent — safe to run multiple times.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path.cwd()

    # ── Public API ────────────────────────────────────────────────────────────

    def setup(self, *, force: bool = False) -> BootstrapResult:
        """Full first-run bootstrap: workspace + config + providers + models."""
        result = BootstrapResult()

        # Check if already bootstrapped (skip unless forced)
        manifest = load_manifest(self._base_dir)
        if not force and is_manifest_current(manifest):
            logger.info("Bootstrap already complete (use --force to re-run)")
            result.add(
                CheckResult(
                    name="bootstrap:manifest",
                    status=CheckStatus.OK,
                    message="Previously bootstrapped — all checks skipped (use --force to re-run)",
                )
            )
            return result

        logger.info("Starting bootstrap setup...")

        # 1. Environment
        logger.info("Phase 1: Environment checks")
        for check in check_environment():
            result.add(check)

        # 2. Workspace
        logger.info("Phase 2: Workspace bootstrap")
        for check in bootstrap_workspace(self._base_dir):
            result.add(check)
            if check.repaired:
                result.repairs.append(check.message)

        # 3. Configuration
        logger.info("Phase 3: Configuration validation")
        migrations = migrate_config(self._base_dir)
        result.repairs.extend(migrations)
        for check in validate_config(self._base_dir):
            result.add(check)

        # 4. Providers
        logger.info("Phase 4: Provider validation")
        for check in validate_providers():
            result.add(check)

        # 5. Model bootstrap
        logger.info("Phase 5: Model bootstrap")
        for check in bootstrap_models(self._base_dir):
            result.add(check)

        # 6. Build + save manifest
        manifest = build_manifest(self._base_dir)
        manifest["setup_success"] = result.success
        save_manifest(manifest, self._base_dir)

        # 7. Environment report
        write_environment_report(result, self._base_dir)

        return result

    def doctor(self) -> BootstrapResult:
        """Full health check for a running environment. Never mutates state."""
        result = BootstrapResult()

        for check in check_environment():
            result.add(check)

        for check in validate_config(self._base_dir):
            result.add(check)

        for check in validate_providers():
            result.add(check)

        for check in bootstrap_models(self._base_dir):
            result.add(check)

        write_environment_report(result, self._base_dir)
        return result

    def validate(self) -> BootstrapResult:
        """Lightweight config + provider validation only."""
        result = BootstrapResult()
        for check in validate_config(self._base_dir):
            result.add(check)
        for check in validate_providers():
            result.add(check)
        return result

    def repair(self) -> BootstrapResult:
        """Run the self-healing engine: fix directories, permissions, symlinks."""
        result = BootstrapResult()
        for check in heal(self._base_dir):
            result.add(check)
            if check.repaired:
                result.repairs.append(check.message)
        # Also ensure workspace dirs exist
        for check in bootstrap_workspace(self._base_dir):
            result.add(check)
            if check.repaired:
                result.repairs.append(check.message)
        return result

    def version_info(self) -> dict:
        """Return current version info + manifest."""
        manifest = load_manifest(self._base_dir)
        fresh = build_manifest(self._base_dir)
        return {
            "current": fresh,
            "manifest": manifest,
            "manifest_current": is_manifest_current(manifest),
        }
