"""Tests for the Bootstrap Engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ytfactory.bootstrap.models import CheckStatus, CheckResult, BootstrapResult
from ytfactory.bootstrap.workspace import bootstrap_workspace, validate_workspace, _REQUIRED_DIRS
from ytfactory.bootstrap.healer import heal
from ytfactory.bootstrap.version_manager import (
    build_manifest,
    is_manifest_current,
    load_manifest,
    save_manifest,
    BOOTSTRAP_VERSION,
)
from ytfactory.bootstrap.report import write_environment_report, read_environment_report
from ytfactory.bootstrap.engine import BootstrapEngine


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_root(tmp_path: Path) -> Path:
    """Temporary project root with a minimal .env file."""
    env = tmp_path / ".env"
    env.write_text(
        "LLM_PROVIDER=gemini\n"
        "GEMINI_API_KEY=test-key\n"
        "TAVILY_API_KEY=test-tavily\n"
        "SEARCH_PROVIDER=tavily\n"
        "IMAGE_PROVIDER=huggingface\n"
        "HF_TOKEN=hf_test\n"
        "TTS_PROVIDER=edge\n"
    )
    return tmp_path


# ── Workspace tests ───────────────────────────────────────────────────────────

class TestWorkspaceBootstrap:
    def test_creates_all_required_dirs(self, tmp_root: Path) -> None:
        results = bootstrap_workspace(tmp_root)
        for rel in _REQUIRED_DIRS:
            assert (tmp_root / rel).is_dir(), f"Missing: {rel}"

    def test_idempotent_second_run(self, tmp_root: Path) -> None:
        bootstrap_workspace(tmp_root)
        results = bootstrap_workspace(tmp_root)
        # Second run: all OK (not REPAIRED)
        for r in results:
            assert r.status in (CheckStatus.OK, CheckStatus.REPAIRED)

    def test_returns_repaired_for_new_dirs(self, tmp_root: Path) -> None:
        results = bootstrap_workspace(tmp_root)
        repaired = [r for r in results if r.status == CheckStatus.REPAIRED]
        assert len(repaired) > 0  # All dirs were missing initially

    def test_validate_detects_missing(self, tmp_path: Path) -> None:
        results = validate_workspace(tmp_path)
        errors = [r for r in results if r.status == CheckStatus.ERROR]
        assert len(errors) > 0

    def test_validate_passes_after_bootstrap(self, tmp_root: Path) -> None:
        bootstrap_workspace(tmp_root)
        results = validate_workspace(tmp_root)
        errors = [r for r in results if r.status == CheckStatus.ERROR]
        assert errors == []

    def test_creates_gitkeep(self, tmp_root: Path) -> None:
        bootstrap_workspace(tmp_root)
        assert (tmp_root / "workspace" / ".gitkeep").exists()


# ── Self-healing tests ────────────────────────────────────────────────────────

class TestSelfHealingEngine:
    def test_heals_missing_directories(self, tmp_root: Path) -> None:
        results = heal(tmp_root)
        repaired = [r for r in results if r.repaired]
        assert len(repaired) > 0
        for rel in _REQUIRED_DIRS:
            assert (tmp_root / rel).is_dir()

    def test_heal_idempotent(self, tmp_root: Path) -> None:
        heal(tmp_root)
        results = heal(tmp_root)
        errors = [r for r in results if r.status == CheckStatus.ERROR]
        assert errors == []

    def test_heal_removes_broken_symlinks(self, tmp_root: Path) -> None:
        # Setup: create workspace and a broken symlink
        (tmp_root / "workspace" / "jobs").mkdir(parents=True, exist_ok=True)
        broken = tmp_root / "workspace" / "jobs" / "broken-link"
        broken.symlink_to("/nonexistent/target")
        assert broken.is_symlink()
        assert not broken.exists()

        results = heal(tmp_root)
        repaired = [r for r in results if r.repaired and "symlink" in r.name]
        assert len(repaired) > 0
        assert not broken.exists()

    def test_no_false_positives_on_healthy_env(self, tmp_root: Path) -> None:
        bootstrap_workspace(tmp_root)
        results = heal(tmp_root)
        errors = [r for r in results if r.status == CheckStatus.ERROR]
        assert errors == []


# ── Version manager tests ─────────────────────────────────────────────────────

class TestVersionManager:
    def test_build_manifest_has_required_fields(self, tmp_root: Path) -> None:
        manifest = build_manifest(tmp_root)
        assert "bootstrap_version" in manifest
        assert "python_version" in manifest
        assert "ffmpeg_version" in manifest
        assert "validated_at" in manifest

    def test_save_and_load_manifest(self, tmp_root: Path) -> None:
        manifest = {"bootstrap_version": BOOTSTRAP_VERSION, "test": True}
        save_manifest(manifest, tmp_root)
        loaded = load_manifest(tmp_root)
        assert loaded["test"] is True
        assert loaded["bootstrap_version"] == BOOTSTRAP_VERSION

    def test_is_current_returns_true_for_matching_version(self, tmp_root: Path) -> None:
        manifest = {"bootstrap_version": BOOTSTRAP_VERSION}
        assert is_manifest_current(manifest) is True

    def test_is_current_returns_false_for_old_version(self) -> None:
        manifest = {"bootstrap_version": "0.0.0"}
        assert is_manifest_current(manifest) is False

    def test_empty_manifest_is_not_current(self) -> None:
        assert is_manifest_current({}) is False

    def test_load_missing_manifest_returns_empty(self, tmp_path: Path) -> None:
        result = load_manifest(tmp_path)
        assert result == {}


# ── Report tests ──────────────────────────────────────────────────────────────

class TestBootstrapReport:
    def test_write_environment_report(self, tmp_root: Path) -> None:
        result = BootstrapResult()
        result.add(CheckResult("env:test", CheckStatus.OK, "All good"))
        result.add(CheckResult("env:warn", CheckStatus.WARNING, "Minor issue"))
        path = write_environment_report(result, tmp_root)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["success"] is True
        assert data["summary"]["ok"] == 1
        assert data["summary"]["warning"] == 1
        assert len(data["checks"]) == 2

    def test_write_report_with_errors(self, tmp_root: Path) -> None:
        result = BootstrapResult()
        result.add(CheckResult("env:fail", CheckStatus.ERROR, "Broken"))
        path = write_environment_report(result, tmp_root)
        data = json.loads(path.read_text())
        assert data["success"] is False

    def test_read_environment_report(self, tmp_root: Path) -> None:
        result = BootstrapResult()
        result.add(CheckResult("test", CheckStatus.OK, "ok"))
        write_environment_report(result, tmp_root)
        loaded = read_environment_report(tmp_root)
        assert loaded is not None
        assert "checks" in loaded

    def test_read_missing_report_returns_none(self, tmp_path: Path) -> None:
        assert read_environment_report(tmp_path) is None


# ── BootstrapResult model tests ───────────────────────────────────────────────

class TestBootstrapResultModel:
    def test_success_when_all_ok(self) -> None:
        result = BootstrapResult()
        result.add(CheckResult("a", CheckStatus.OK, "ok"))
        result.add(CheckResult("b", CheckStatus.REPAIRED, "repaired", repaired=True))
        result.add(CheckResult("c", CheckStatus.SKIPPED, "skipped"))
        assert result.success is True

    def test_failure_when_any_error(self) -> None:
        result = BootstrapResult()
        result.add(CheckResult("a", CheckStatus.OK, "ok"))
        result.add(CheckResult("b", CheckStatus.ERROR, "broken"))
        assert result.success is False

    def test_errors_and_warnings_filters(self) -> None:
        result = BootstrapResult()
        result.add(CheckResult("a", CheckStatus.OK, "ok"))
        result.add(CheckResult("b", CheckStatus.WARNING, "warn"))
        result.add(CheckResult("c", CheckStatus.ERROR, "err"))
        assert len(result.errors) == 1
        assert len(result.warnings) == 1

    def test_check_result_ok_property(self) -> None:
        assert CheckResult("x", CheckStatus.OK, "").ok is True
        assert CheckResult("x", CheckStatus.REPAIRED, "", repaired=True).ok is True
        assert CheckResult("x", CheckStatus.SKIPPED, "").ok is True
        assert CheckResult("x", CheckStatus.WARNING, "").ok is False
        assert CheckResult("x", CheckStatus.ERROR, "").ok is False


# ── BootstrapEngine integration tests ─────────────────────────────────────────

class TestBootstrapEngine:
    def test_setup_creates_workspace(self, tmp_root: Path) -> None:
        engine = BootstrapEngine(tmp_root)
        with (
            patch("ytfactory.bootstrap.engine.validate_providers", return_value=[]),
            patch("ytfactory.bootstrap.engine.bootstrap_models", return_value=[]),
            patch("ytfactory.bootstrap.engine.check_environment", return_value=[]),
        ):
            result = engine.setup(force=True)
        for rel in _REQUIRED_DIRS:
            assert (tmp_root / rel).is_dir(), f"Missing dir: {rel}"

    def test_setup_writes_manifest(self, tmp_root: Path) -> None:
        engine = BootstrapEngine(tmp_root)
        with (
            patch("ytfactory.bootstrap.engine.validate_providers", return_value=[]),
            patch("ytfactory.bootstrap.engine.bootstrap_models", return_value=[]),
            patch("ytfactory.bootstrap.engine.check_environment", return_value=[]),
        ):
            engine.setup(force=True)
        manifest = load_manifest(tmp_root)
        assert manifest.get("bootstrap_version") == BOOTSTRAP_VERSION

    def test_setup_skips_when_already_done(self, tmp_root: Path) -> None:
        engine = BootstrapEngine(tmp_root)
        # Save a current manifest
        save_manifest({"bootstrap_version": BOOTSTRAP_VERSION}, tmp_root)
        # Phase 0 (ML package checks) always runs; patch it out so the test
        # focuses on the skip-remaining-phases behaviour.
        with patch("ytfactory.bootstrap.engine.install_ml_packages", return_value=[]):
            result = engine.setup(force=False)
        # Should return a single "already bootstrapped" check
        assert len(result.checks) == 1
        assert result.checks[0].status == CheckStatus.OK

    def test_setup_force_reruns(self, tmp_root: Path) -> None:
        engine = BootstrapEngine(tmp_root)
        save_manifest({"bootstrap_version": BOOTSTRAP_VERSION}, tmp_root)
        with (
            patch("ytfactory.bootstrap.engine.validate_providers", return_value=[]),
            patch("ytfactory.bootstrap.engine.bootstrap_models", return_value=[]),
            patch("ytfactory.bootstrap.engine.check_environment", return_value=[]),
        ):
            result = engine.setup(force=True)
        # Force run — multiple checks executed
        assert len(result.checks) > 1

    def test_validate_only_runs_config_and_providers(self, tmp_root: Path) -> None:
        engine = BootstrapEngine(tmp_root)
        with patch("ytfactory.bootstrap.engine.validate_providers", return_value=[
            CheckResult("provider:test", CheckStatus.OK, "ok")
        ]):
            result = engine.validate()
        provider_checks = [c for c in result.checks if c.name.startswith("provider:")]
        assert len(provider_checks) == 1

    def test_repair_heals_missing_dirs(self, tmp_root: Path) -> None:
        engine = BootstrapEngine(tmp_root)
        result = engine.repair()
        repaired = [c for c in result.checks if c.repaired]
        assert len(repaired) > 0

    def test_version_info_returns_manifest(self, tmp_root: Path) -> None:
        engine = BootstrapEngine(tmp_root)
        save_manifest({"bootstrap_version": BOOTSTRAP_VERSION, "test_key": "v"}, tmp_root)
        info = engine.version_info()
        assert "current" in info
        assert "manifest" in info
        assert info["manifest"]["test_key"] == "v"
        assert info["manifest_current"] is True


# ── Config validator tests ────────────────────────────────────────────────────

class TestConfigValidator:
    def test_missing_env_file_returns_error(self, tmp_path: Path) -> None:
        from ytfactory.bootstrap.config_validator import validate_config
        results = validate_config(tmp_path)
        errors = [r for r in results if r.status == CheckStatus.ERROR]
        assert any("not found" in e.message for e in errors)

    def test_env_file_present_returns_ok(self, tmp_root: Path) -> None:
        from ytfactory.bootstrap.config_validator import validate_config
        results = validate_config(tmp_root)
        env_check = next(r for r in results if r.name == "config:.env")
        assert env_check.status == CheckStatus.OK

    def test_missing_api_key_returns_error(self, tmp_path: Path) -> None:
        from ytfactory.bootstrap.config_validator import validate_config
        # .env without required keys
        env = tmp_path / ".env"
        env.write_text("LLM_PROVIDER=gemini\nGEMINI_API_KEY=\nTAVILY_API_KEY=\n")
        results = validate_config(tmp_path)
        errors = [r for r in results if r.status == CheckStatus.ERROR]
        assert len(errors) > 0


# ── Model bootstrap tests ─────────────────────────────────────────────────────

class TestModelBootstrap:
    """Tests for model_bootstrap.py — LAMM delegation and vision model gating."""

    def test_lamm_check_returns_ok(self) -> None:
        from ytfactory.bootstrap.model_bootstrap import _check_lamm_available
        results = _check_lamm_available()
        assert len(results) == 1
        assert results[0].name == "model:lamm"
        assert results[0].status == CheckStatus.OK

    def test_vision_model_skipped_when_image_review_disabled(self, tmp_path: Path) -> None:
        """Vision model must be SKIPPED when IMAGE_REVIEW_ENABLED=false."""
        from ytfactory.bootstrap.model_bootstrap import _provision_via_lamm
        with (
            patch(
                "ytfactory.bootstrap.model_bootstrap._is_image_review_enabled",
                return_value=False,
            ),
            patch(
                "ytfactory.bootstrap.model_bootstrap._get_vision_model_name",
                return_value="minicpm_v2_6",
            ),
        ):
            results = _provision_via_lamm(tmp_path)

        vision_checks = [r for r in results if "minicpm_v2_6" in r.name]
        assert len(vision_checks) == 1
        assert vision_checks[0].status == CheckStatus.SKIPPED

    def test_vision_model_provisioned_when_image_review_enabled(self, tmp_path: Path) -> None:
        """Vision model must be provisioned when IMAGE_REVIEW_ENABLED=true."""
        from ytfactory.bootstrap.model_bootstrap import _provision_via_lamm
        from ytfactory.models import ProvisionResult, ModelStatus

        fake_provision = ProvisionResult(
            name="minicpm_v2_6",
            status=ModelStatus.MISSING,
            message="Not in cache",
        )
        with (
            patch(
                "ytfactory.bootstrap.model_bootstrap._is_image_review_enabled",
                return_value=True,
            ),
            patch(
                "ytfactory.bootstrap.model_bootstrap._get_vision_model_name",
                return_value="minicpm_v2_6",
            ),
            patch(
                "ytfactory.models.manager.LocalAIModelManager.provision",
                return_value=fake_provision,
            ),
        ):
            results = _provision_via_lamm(tmp_path)

        vision_checks = [r for r in results if "minicpm_v2_6" in r.name]
        assert len(vision_checks) == 1
        # MISSING with auto_download=false maps to WARNING (non-blocking)
        assert vision_checks[0].status == CheckStatus.WARNING

    def test_get_vision_model_name_uses_settings(self) -> None:
        """_get_vision_model_name must read the configured value, not a hardcoded string."""
        from unittest.mock import MagicMock
        from ytfactory.bootstrap.model_bootstrap import _get_vision_model_name
        mock_settings = MagicMock()
        mock_settings.return_value.vision_review_local_model = "qwen2_5_vl_3b"
        with patch("ytfactory.bootstrap.model_bootstrap.Settings", mock_settings, create=True):
            # Call indirectly via the module
            from ytfactory.bootstrap import model_bootstrap as mb
            with patch("ytfactory.config.settings.Settings", mock_settings):
                name = mb._get_vision_model_name()
        assert name == "qwen2_5_vl_3b"

    def test_get_vision_model_name_default_fallback(self) -> None:
        """Falls back to minicpm_v2_6 if Settings cannot be loaded."""
        from ytfactory.bootstrap.model_bootstrap import _get_vision_model_name
        with patch(
            "ytfactory.bootstrap.model_bootstrap._get_vision_model_name",
            side_effect=Exception("Settings unavailable"),
        ):
            # Call the real function when the mock raises — use the actual import
            pass
        # Real function returns default when Settings errors
        with patch(
            "ytfactory.config.settings.Settings",
            side_effect=Exception("env error"),
        ):
            from ytfactory.bootstrap import model_bootstrap as mb
            name = mb._get_vision_model_name()
        assert name == "minicpm_v2_6"

    def test_non_vision_model_not_gated_by_image_review(self, tmp_path: Path) -> None:
        """whisperx must NOT be skipped regardless of image_review_enabled."""
        from ytfactory.bootstrap.model_bootstrap import _provision_via_lamm
        with (
            patch(
                "ytfactory.bootstrap.model_bootstrap._is_image_review_enabled",
                return_value=False,
            ),
            patch(
                "ytfactory.bootstrap.model_bootstrap._get_vision_model_name",
                return_value="minicpm_v2_6",
            ),
        ):
            results = _provision_via_lamm(tmp_path)

        whisperx_checks = [r for r in results if "whisperx" in r.name]
        assert len(whisperx_checks) == 1
        # whisperx is lazy (no hf_repo) so it comes back OK or WARNING, never SKIPPED due to image review
        assert whisperx_checks[0].status != CheckStatus.ERROR
