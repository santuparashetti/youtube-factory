"""Tests for the Local AI Model Manager."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_core.models import LocalAIModelManager, ModelStatus, ProvisionResult
from video_core.models.backend import Backend, select_backend
from video_core.models.manifest import (
    get_state,
    load_manifest,
    save_manifest,
    update_state,
)
from video_core.models.models import ModelState
from video_core.models.registry import load_registry


# ── Registry tests ─────────────────────────────────────────────────────────────

class TestRegistry:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """
models:
  test_model:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/test-model"
    description: "Test model"
    requires_packages: []
    backends: [cpu]
"""
        registry_file = tmp_path / "models-registry.yaml"
        registry_file.write_text(yaml_content)
        registry = load_registry(registry_file)
        assert "test_model" in registry
        entry = registry["test_model"]
        assert entry.hf_repo == "org/test-model"
        assert entry.backends == ["cpu"]
        assert not entry.required

    def test_missing_yaml_returns_empty(self, tmp_path: Path) -> None:
        registry = load_registry(tmp_path / "nonexistent.yaml")
        assert registry == {}

    def test_builtin_defaults_when_no_yaml(self) -> None:
        """load_registry falls back to builtin defaults if yaml is missing."""
        from video_core.models.registry import _builtin_defaults
        defaults = _builtin_defaults()
        assert "minicpm_v2_6" in defaults
        assert "whisperx" in defaults

    def test_default_registry_loads(self) -> None:
        """Default config/models-registry.yaml loads without error."""
        registry = load_registry()  # uses default path
        assert len(registry) >= 2
        assert "minicpm_v2_6" in registry
        assert "whisperx" in registry


# ── Backend selection tests ───────────────────────────────────────────────────

class TestBackendSelection:
    def test_cpu_always_available(self) -> None:
        backend = select_backend(["cpu"])
        assert backend == Backend.CPU

    def test_prefers_cuda_when_available(self) -> None:
        with patch("video_core.models.backend._cuda_available", return_value=True):
            backend = select_backend(["cuda", "cpu"])
        assert backend == Backend.CUDA

    def test_falls_back_to_cpu_without_cuda(self) -> None:
        with (
            patch("video_core.models.backend._cuda_available", return_value=False),
            patch("video_core.models.backend._mps_available", return_value=False),
        ):
            backend = select_backend(["cuda", "mps", "cpu"])
        assert backend == Backend.CPU

    def test_mps_selected_when_cuda_unavailable(self) -> None:
        with (
            patch("video_core.models.backend._cuda_available", return_value=False),
            patch("video_core.models.backend._mps_available", return_value=True),
        ):
            backend = select_backend(["cuda", "mps", "cpu"])
        assert backend == Backend.MPS

    def test_restricted_to_cpu_only(self) -> None:
        backend = select_backend(["cpu"])
        assert backend == Backend.CPU


# ── Manifest tests ────────────────────────────────────────────────────────────

class TestManifest:
    def test_save_and_load(self, tmp_path: Path) -> None:
        state = ModelState(
            name="test_model",
            status=ModelStatus.VERIFIED,
            backend="cpu",
            cache_path="/tmp/model",
            packages_ok=True,
        )
        save_manifest(tmp_path, {"test_model": state})
        loaded = load_manifest(tmp_path)
        assert "test_model" in loaded
        assert loaded["test_model"].status == ModelStatus.VERIFIED
        assert loaded["test_model"].cache_path == "/tmp/model"

    def test_load_missing_returns_empty(self, tmp_path: Path) -> None:
        result = load_manifest(tmp_path)
        assert result == {}

    def test_update_state(self, tmp_path: Path) -> None:
        state = ModelState(name="m", status=ModelStatus.MISSING)
        update_state(tmp_path, state)
        loaded = get_state(tmp_path, "m")
        assert loaded is not None
        assert loaded.status == ModelStatus.MISSING

    def test_get_state_unknown(self, tmp_path: Path) -> None:
        result = get_state(tmp_path, "nonexistent")
        assert result is None

    def test_idempotent_update(self, tmp_path: Path) -> None:
        state1 = ModelState(name="m", status=ModelStatus.MISSING)
        state2 = ModelState(name="m", status=ModelStatus.VERIFIED, backend="cuda")
        update_state(tmp_path, state1)
        update_state(tmp_path, state2)
        loaded = get_state(tmp_path, "m")
        assert loaded is not None
        assert loaded.status == ModelStatus.VERIFIED
        assert loaded.backend == "cuda"


# ── LocalAIModelManager tests ─────────────────────────────────────────────────

class TestLocalAIModelManager:
    def _make_manager(self, tmp_path: Path) -> LocalAIModelManager:
        """Build a LAMM pointing at a minimal test registry."""
        yaml_content = """
models:
  lazy_model:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "Lazy test model"
    requires_packages: []
    backends: [cpu]

  disabled_model:
    enabled: false
    required: false
    auto_download: false
    hf_repo: "org/disabled"
    description: "Disabled test model"
    requires_packages: []
    backends: [cpu]

  pkg_model:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/pkg-model"
    description: "Model with package requirement"
    requires_packages: [_nonexistent_package_xyz_]
    backends: [cpu]
"""
        registry_file = tmp_path / "registry.yaml"
        registry_file.write_text(yaml_content)
        return LocalAIModelManager(base_dir=tmp_path, registry_path=registry_file)

    def test_provision_unknown_model(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        result = manager.provision("nonexistent_model")
        assert result.status == ModelStatus.ERROR
        assert "not found in registry" in result.message

    def test_provision_disabled_model(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        result = manager.provision("disabled_model")
        assert result.skipped

    def test_provision_missing_packages(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        result = manager.provision("pkg_model")
        assert result.status == ModelStatus.MISSING
        assert "_nonexistent_package_xyz_" in result.message

    def test_provision_lazy_model_no_hf_repo(self, tmp_path: Path) -> None:
        """Lazy models (no hf_repo) always verify successfully."""
        manager = self._make_manager(tmp_path)
        result = manager.provision("lazy_model")
        assert result.ok
        assert "first use" in result.message.lower()

    def test_provision_already_verified_skips_recheck(self, tmp_path: Path) -> None:
        """Second provision call returns cached state without re-checking."""
        manager = self._make_manager(tmp_path)
        # Manually mark as verified
        update_state(tmp_path, ModelState(
            name="lazy_model",
            status=ModelStatus.VERIFIED,
            backend="cpu",
            packages_ok=True,
        ))
        result = manager.provision("lazy_model")
        assert result.status == ModelStatus.VERIFIED
        assert result.message == "Already verified"

    def test_provision_force_reruns(self, tmp_path: Path) -> None:
        """force=True ignores cached state and re-provisions."""
        manager = self._make_manager(tmp_path)
        update_state(tmp_path, ModelState(
            name="lazy_model",
            status=ModelStatus.VERIFIED,
            backend="cpu",
        ))
        result = manager.provision("lazy_model", force=True)
        # Should re-verify (lazy model with no hf_repo → verify from cache)
        assert result.ok

    def test_status_returns_unknown_for_fresh(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        state = manager.status("lazy_model")
        assert state.status == ModelStatus.UNKNOWN

    def test_diagnostics_returns_all_registry_entries(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        diag = manager.diagnostics()
        names = {d["name"] for d in diag}
        assert "lazy_model" in names
        assert "disabled_model" in names

    def test_heal_triggers_force_provision(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        result = manager.heal("lazy_model")
        assert result.ok

    def test_provision_all_skips_disabled(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        results = manager.provision_all()
        names = {r.name for r in results}
        assert "disabled_model" not in names  # disabled entries skipped by provision_all

    def test_get_backend_defaults_to_cpu(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path)
        backend = manager.get_backend("lazy_model")
        assert backend == Backend.CPU


# ── ProvisionResult tests ─────────────────────────────────────────────────────

class TestProvisionResult:
    def test_ok_verified(self) -> None:
        r = ProvisionResult(name="m", status=ModelStatus.VERIFIED, backend="cpu")
        assert r.ok

    def test_ok_skipped(self) -> None:
        r = ProvisionResult(name="m", status=ModelStatus.SKIPPED, skipped=True)
        assert r.ok

    def test_not_ok_error(self) -> None:
        r = ProvisionResult(name="m", status=ModelStatus.ERROR)
        assert not r.ok

    def test_not_ok_missing(self) -> None:
        r = ProvisionResult(name="m", status=ModelStatus.MISSING)
        assert not r.ok
