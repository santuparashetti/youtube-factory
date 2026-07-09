"""Tests for the Model Bundle Architecture.

Covers: BundleRuntime/FailureReason enums, BundleArtifact/ModelBundle types,
capabilities validation, ContentAddressedCache, checksum helpers, per-bundle
locking, BundleProvisioner LAZY path, registry parsing of new fields, manifest
v2 round-trip, and LocalAIModelManager bundle API.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.models import (
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
from ytfactory.models.bundle import (
    BundleProvisioner,
    ContentAddressedCache,
    compute_sha256,
    get_bundle_lock,
    verify_checksum,
)
from ytfactory.models.capabilities import (
    capability_error_message,
    format_missing,
    validate_capabilities,
)
from ytfactory.models.manifest import load_manifest, save_manifest
from ytfactory.models.registry import _builtin_defaults, load_registry


# ── BundleRuntime enum ────────────────────────────────────────────────────────

class TestBundleRuntime:
    def test_values_are_strings(self) -> None:
        assert BundleRuntime.TRANSFORMERS == "transformers"
        assert BundleRuntime.LLAMA_CPP == "llama_cpp"
        assert BundleRuntime.LAZY == "lazy"

    def test_round_trip(self) -> None:
        for rt in BundleRuntime:
            assert BundleRuntime(rt.value) is rt

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            BundleRuntime("unknown_runtime")


# ── FailureReason enum ────────────────────────────────────────────────────────

class TestFailureReason:
    def test_all_values_present(self) -> None:
        expected = {
            "DOWNLOAD_FAILED",
            "DISK_FULL",
            "CHECKSUM_MISMATCH",
            "INCOMPATIBLE_BUNDLE",
            "MISSING_CAPABILITY",
            "VALIDATION_TIMEOUT",
        }
        assert {r.value for r in FailureReason} == expected

    def test_is_string_enum(self) -> None:
        assert isinstance(FailureReason.DOWNLOAD_FAILED, str)
        assert FailureReason.DISK_FULL == "DISK_FULL"


# ── BundleArtifact dataclass ──────────────────────────────────────────────────

class TestBundleArtifact:
    def test_defaults(self) -> None:
        a = BundleArtifact(name="weights", file="model.gguf")
        assert a.revision is None
        assert a.checksum is None
        assert a.compatible_with == []

    def test_fields_stored(self) -> None:
        a = BundleArtifact(
            name="text_model",
            file="text.gguf",
            revision="abc123",
            checksum="sha256:" + "a" * 64,
            compatible_with=["llama.cpp>=0.2"],
        )
        assert a.name == "text_model"
        assert a.checksum.startswith("sha256:")
        assert "llama.cpp>=0.2" in a.compatible_with


# ── WarmInferenceConfig dataclass ─────────────────────────────────────────────

class TestWarmInferenceConfig:
    def test_defaults(self) -> None:
        w = WarmInferenceConfig()
        assert w.sample_image == ""
        assert "Describe" in w.sample_prompt

    def test_custom_fields(self) -> None:
        w = WarmInferenceConfig(sample_image="bundled://sample.jpg", sample_prompt="What color?")
        assert w.sample_image == "bundled://sample.jpg"
        assert w.sample_prompt == "What color?"


# ── ModelBundle dataclass ─────────────────────────────────────────────────────

class TestModelBundle:
    def test_minimal(self) -> None:
        b = ModelBundle(runtime=BundleRuntime.LAZY, artifacts={})
        assert b.capabilities == []
        assert b.warm_inference is None
        assert b.auto_validate is False

    def test_full(self) -> None:
        art = BundleArtifact(name="m", file="m.gguf")
        w = WarmInferenceConfig()
        b = ModelBundle(
            runtime=BundleRuntime.LLAMA_CPP,
            artifacts={"m": art},
            capabilities=["image_review"],
            warm_inference=w,
            auto_validate=True,
        )
        assert b.runtime == BundleRuntime.LLAMA_CPP
        assert "m" in b.artifacts
        assert "image_review" in b.capabilities
        assert b.auto_validate is True


# ── ModelEntry bundle fields ──────────────────────────────────────────────────

class TestModelEntryBundleFields:
    def test_defaults_backward_compat(self) -> None:
        e = ModelEntry(
            name="old_model",
            enabled=True,
            required=False,
            auto_download=False,
            hf_repo="org/old",
            description="legacy",
        )
        assert e.capabilities == []
        assert e.runtime == BundleRuntime.TRANSFORMERS
        assert e.bundle is None

    def test_with_bundle(self) -> None:
        bundle = ModelBundle(runtime=BundleRuntime.LAZY, artifacts={})
        e = ModelEntry(
            name="new_model",
            enabled=True,
            required=False,
            auto_download=False,
            hf_repo="",
            description="lazy model",
            runtime=BundleRuntime.LAZY,
            capabilities=["asr"],
            bundle=bundle,
        )
        assert e.runtime == BundleRuntime.LAZY
        assert "asr" in e.capabilities
        assert e.bundle is not None


# ── ModelState bundle fields ──────────────────────────────────────────────────

class TestModelStateBundleFields:
    def test_defaults_backward_compat(self) -> None:
        s = ModelState(name="m", status=ModelStatus.VERIFIED)
        assert s.capabilities == []
        assert s.checksum_verified is False
        assert s.warm_inference_ok is False
        assert s.bundle_artifacts == {}
        assert s.failure_reason == ""

    def test_can_set_all_fields(self) -> None:
        s = ModelState(
            name="m",
            status=ModelStatus.VERIFIED,
            capabilities=["image_review"],
            checksum_verified=True,
            warm_inference_ok=True,
            bundle_artifacts={"text_model": "/path/to/file.gguf"},
            failure_reason="",
        )
        assert s.checksum_verified is True
        assert "image_review" in s.capabilities
        assert "/path/to/file.gguf" in s.bundle_artifacts.values()


# ── ProvisionResult bundle fields ─────────────────────────────────────────────

class TestProvisionResultBundleFields:
    def test_defaults_backward_compat(self) -> None:
        r = ProvisionResult(name="m", status=ModelStatus.VERIFIED)
        assert r.failure_reason == ""
        assert r.capabilities == []
        assert r.bundle_artifacts == {}
        assert r.checksum_verified is False

    def test_ok_property(self) -> None:
        assert ProvisionResult(name="m", status=ModelStatus.VERIFIED).ok is True
        assert ProvisionResult(name="m", status=ModelStatus.SKIPPED).ok is True
        assert ProvisionResult(name="m", status=ModelStatus.ERROR).ok is False


# ── __init__.py exports ───────────────────────────────────────────────────────

class TestPackageExports:
    def test_all_new_types_exported(self) -> None:
        import ytfactory.models as mod
        for name in (
            "BundleRuntime",
            "FailureReason",
            "BundleArtifact",
            "WarmInferenceConfig",
            "ModelBundle",
        ):
            assert hasattr(mod, name), f"Missing export: {name}"

    def test_existing_exports_still_present(self) -> None:
        import ytfactory.models as mod
        for name in ("LocalAIModelManager", "Backend", "ModelEntry", "ModelState", "ModelStatus", "ProvisionResult"):
            assert hasattr(mod, name)


# ── validate_capabilities ─────────────────────────────────────────────────────

class TestValidateCapabilities:
    def test_all_satisfied(self) -> None:
        missing = validate_capabilities(["image_review", "structured_json"], ["image_review"])
        assert missing == []

    def test_some_missing(self) -> None:
        missing = validate_capabilities(["structured_json"], ["image_review", "structured_json"])
        assert missing == ["image_review"]

    def test_all_missing(self) -> None:
        missing = validate_capabilities([], ["image_review", "structured_json"])
        assert set(missing) == {"image_review", "structured_json"}

    def test_empty_required(self) -> None:
        missing = validate_capabilities([], [])
        assert missing == []

    def test_extra_declared_ok(self) -> None:
        missing = validate_capabilities(["a", "b", "c"], ["a"])
        assert missing == []


class TestFormatMissing:
    def test_single(self) -> None:
        result = format_missing(["image_review"])
        assert result == "MISSING_CAPABILITY(image_review)"

    def test_multiple(self) -> None:
        result = format_missing(["cap_a", "cap_b"])
        assert "MISSING_CAPABILITY(cap_a)" in result
        assert "MISSING_CAPABILITY(cap_b)" in result

    def test_empty(self) -> None:
        assert format_missing([]) == ""


class TestCapabilityErrorMessage:
    def test_format(self) -> None:
        msg = capability_error_message("mymodel", ["image_review"])
        assert "mymodel" in msg
        assert "MISSING_CAPABILITY(image_review)" in msg

    def test_multiple_missing(self) -> None:
        msg = capability_error_message("m", ["a", "b"])
        assert "MISSING_CAPABILITY(a)" in msg
        assert "MISSING_CAPABILITY(b)" in msg


# ── compute_sha256 / verify_checksum ──────────────────────────────────────────

class TestChecksumHelpers:
    def test_compute_sha256(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert compute_sha256(f) == expected

    def test_verify_checksum_match(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"test")
        digest = hashlib.sha256(b"test").hexdigest()
        assert verify_checksum(f, f"sha256:{digest}") is True

    def test_verify_checksum_mismatch(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"test")
        assert verify_checksum(f, "sha256:" + "0" * 64) is False

    def test_verify_checksum_empty_accepts(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"anything")
        assert verify_checksum(f, "") is True
        assert verify_checksum(f, None) is True  # type: ignore[arg-type]

    def test_verify_checksum_unsupported_format(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"x")
        # non-sha256 format accepted without verification (logged warning)
        assert verify_checksum(f, "md5:abc123") is True


# ── get_bundle_lock ───────────────────────────────────────────────────────────

class TestGetBundleLock:
    def test_same_name_returns_same_lock(self) -> None:
        lock_a = get_bundle_lock("model_x")
        lock_b = get_bundle_lock("model_x")
        assert lock_a is lock_b

    def test_different_names_different_locks(self) -> None:
        lock_a = get_bundle_lock("model_alpha_unique")
        lock_b = get_bundle_lock("model_beta_unique")
        assert lock_a is not lock_b

    def test_lock_is_threading_lock(self) -> None:
        lock = get_bundle_lock("model_lock_test")
        assert isinstance(lock, type(threading.Lock()))

    def test_concurrent_access_serialised(self) -> None:
        results: list[int] = []
        lock = get_bundle_lock("concurrent_test_model")

        def acquire_and_record(val: int) -> None:
            with lock:
                results.append(val)
                time.sleep(0.01)

        threads = [threading.Thread(target=acquire_and_record, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sorted(results) == [0, 1, 2]


# ── ContentAddressedCache ─────────────────────────────────────────────────────

class TestContentAddressedCache:
    def test_get_miss_returns_none(self, tmp_path: Path) -> None:
        cache = ContentAddressedCache(tmp_path / "cache")
        assert cache.get("abc123", "model.gguf") is None

    def test_put_and_get(self, tmp_path: Path) -> None:
        cache = ContentAddressedCache(tmp_path / "cache")
        src = tmp_path / "source.gguf"
        src.write_bytes(b"gguf content")
        checksum_hex = "a" * 64
        stored = cache.put(checksum_hex, "source.gguf", src)
        assert stored.exists()
        assert stored.stat().st_size > 0
        retrieved = cache.get(checksum_hex, "source.gguf")
        assert retrieved is not None
        assert retrieved.read_bytes() == b"gguf content"

    def test_path_structure_uses_prefix(self, tmp_path: Path) -> None:
        cache = ContentAddressedCache(tmp_path / "cache")
        src = tmp_path / "m.gguf"
        src.write_bytes(b"data")
        hex_id = "beef" + "0" * 60
        stored = cache.put(hex_id, "m.gguf", src)
        # First 2 chars should be in the path
        assert "be" in str(stored)

    def test_evict_lru_keeps_n(self, tmp_path: Path) -> None:
        cache = ContentAddressedCache(tmp_path / "cache")
        # Insert 7 entries
        for i in range(7):
            src = tmp_path / f"f{i}.gguf"
            src.write_bytes(f"content{i}".encode())
            hex_id = f"{i:02x}" + "0" * 62
            cache.put(hex_id, f"f{i}.gguf", src)

        evicted = cache.evict_lru(keep_n=5)
        assert evicted == 2

    def test_evict_lru_no_op_when_under_limit(self, tmp_path: Path) -> None:
        cache = ContentAddressedCache(tmp_path / "cache2")
        src = tmp_path / "only.gguf"
        src.write_bytes(b"x")
        cache.put("cc" + "0" * 62, "only.gguf", src)
        evicted = cache.evict_lru(keep_n=5)
        assert evicted == 0


# ── BundleProvisioner — LAZY path ─────────────────────────────────────────────

class TestBundleProvisionerLazy:
    def test_lazy_bundle_returns_verified(self, tmp_path: Path) -> None:
        provisioner = BundleProvisioner(tmp_path)
        bundle = ModelBundle(runtime=BundleRuntime.LAZY, artifacts={})
        status, msg, paths, checksum_ok = provisioner.provision(
            "whisperx", bundle, hf_repo="", revision=None
        )
        assert status == ModelStatus.VERIFIED
        assert paths == {}
        assert "Lazy" in msg

    def test_lazy_bundle_checksum_verified_true(self, tmp_path: Path) -> None:
        provisioner = BundleProvisioner(tmp_path)
        bundle = ModelBundle(runtime=BundleRuntime.LAZY, artifacts={})
        _, _, _, checksum_ok = provisioner.provision("lazy_m", bundle, "", None)
        assert checksum_ok is True


# ── BundleProvisioner — TRANSFORMERS path ────────────────────────────────────

class TestBundleProvisionerTransformers:
    def test_transformers_no_hf_repo_passes(self, tmp_path: Path) -> None:
        provisioner = BundleProvisioner(tmp_path)
        bundle = ModelBundle(runtime=BundleRuntime.TRANSFORMERS, artifacts={})
        status, msg, paths, _ = provisioner.provision("m", bundle, hf_repo="", revision=None)
        assert status == ModelStatus.VERIFIED

    def test_transformers_download_success(self, tmp_path: Path) -> None:
        provisioner = BundleProvisioner(tmp_path)
        bundle = ModelBundle(
            runtime=BundleRuntime.TRANSFORMERS,
            artifacts={"text_model": BundleArtifact(name="text_model", file=".")},
        )
        fake_cache = str(tmp_path / "hf_cache")
        Path(fake_cache).mkdir()
        with patch("ytfactory.models.bundle.snapshot_download", return_value=fake_cache, create=True):
            with patch("huggingface_hub.snapshot_download", return_value=fake_cache, create=True):
                status, msg, paths, _ = provisioner.provision(
                    "minicpm", bundle, hf_repo="org/model", revision=None
                )
        assert status == ModelStatus.VERIFIED
        assert "text_model" in paths

    def test_transformers_missing_hf_hub(self, tmp_path: Path) -> None:
        provisioner = BundleProvisioner(tmp_path)
        bundle = ModelBundle(runtime=BundleRuntime.TRANSFORMERS, artifacts={})
        with patch.dict("sys.modules", {"huggingface_hub": None}):
            status, msg, _, _ = provisioner.provision("m", bundle, "org/m", None)
        assert status == ModelStatus.ERROR
        assert FailureReason.DOWNLOAD_FAILED.value in msg


# ── BundleProvisioner — unknown runtime ───────────────────────────────────────

class TestBundleProvisionerUnknownRuntime:
    def test_unknown_runtime_returns_error(self, tmp_path: Path) -> None:
        provisioner = BundleProvisioner(tmp_path)
        # Manually create a bundle with a patched runtime
        bundle = ModelBundle(runtime=BundleRuntime.LAZY, artifacts={})
        bundle.runtime = "totally_unknown"  # type: ignore[assignment]
        status, msg, _, _ = provisioner.provision("m", bundle, "", None)
        assert status == ModelStatus.ERROR
        assert FailureReason.INCOMPATIBLE_BUNDLE.value in msg


# ── Registry parsing — new fields ────────────────────────────────────────────

class TestRegistryBundleFields:
    def _write_registry(self, tmp_path: Path, content: str) -> Path:
        f = tmp_path / "models-registry.yaml"
        f.write_text(content)
        return f

    def test_lazy_runtime_parsed(self, tmp_path: Path) -> None:
        p = self._write_registry(tmp_path, """
models:
  whisperx:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "WhisperX"
    requires_packages: [whisperx]
    backends: [cpu]
    runtime: lazy
    capabilities: []
""")
        registry = load_registry(p)
        assert registry["whisperx"].runtime == BundleRuntime.LAZY
        assert registry["whisperx"].capabilities == []

    def test_transformers_with_capabilities_parsed(self, tmp_path: Path) -> None:
        p = self._write_registry(tmp_path, """
models:
  vision_model:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/vision"
    description: "Vision"
    requires_packages: [torch]
    backends: [cuda, cpu]
    runtime: transformers
    capabilities:
      - image_review
      - structured_json
""")
        registry = load_registry(p)
        entry = registry["vision_model"]
        assert entry.runtime == BundleRuntime.TRANSFORMERS
        assert "image_review" in entry.capabilities
        assert "structured_json" in entry.capabilities

    def test_bundle_artifacts_parsed(self, tmp_path: Path) -> None:
        p = self._write_registry(tmp_path, """
models:
  gguf_model:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/gguf"
    description: "GGUF model"
    requires_packages: []
    backends: [cpu]
    runtime: llama_cpp
    capabilities: [text_gen]
    bundle:
      auto_validate: false
      artifacts:
        text_model:
          file: "model-q4.gguf"
          revision: "abc123"
          checksum: "sha256:dead"
          compatible_with: ["llama.cpp>=0.2"]
""")
        registry = load_registry(p)
        entry = registry["gguf_model"]
        assert entry.runtime == BundleRuntime.LLAMA_CPP
        assert entry.bundle is not None
        assert "text_model" in entry.bundle.artifacts
        art = entry.bundle.artifacts["text_model"]
        assert art.file == "model-q4.gguf"
        assert art.revision == "abc123"
        assert art.checksum == "sha256:dead"
        assert "llama.cpp>=0.2" in art.compatible_with

    def test_warm_inference_parsed(self, tmp_path: Path) -> None:
        p = self._write_registry(tmp_path, """
models:
  m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/m"
    description: "m"
    requires_packages: []
    backends: [cpu]
    runtime: transformers
    capabilities: [image_review]
    bundle:
      auto_validate: true
      warm_inference:
        sample_image: "bundled://sample.jpg"
        sample_prompt: "What is this?"
""")
        registry = load_registry(p)
        entry = registry["m"]
        assert entry.bundle is not None
        assert entry.bundle.auto_validate is True
        wi = entry.bundle.warm_inference
        assert wi is not None
        assert wi.sample_image == "bundled://sample.jpg"
        assert wi.sample_prompt == "What is this?"

    def test_synthetic_bundle_created_when_no_bundle_section(self, tmp_path: Path) -> None:
        p = self._write_registry(tmp_path, """
models:
  legacy:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/legacy"
    description: "Legacy"
    requires_packages: []
    backends: [cpu]
""")
        registry = load_registry(p)
        entry = registry["legacy"]
        # Should have synthetic bundle
        assert entry.bundle is not None
        assert entry.bundle.runtime == BundleRuntime.TRANSFORMERS
        assert "text_model" in entry.bundle.artifacts

    def test_no_hf_repo_infers_lazy(self, tmp_path: Path) -> None:
        p = self._write_registry(tmp_path, """
models:
  lazy_no_repo:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "Lazy"
    requires_packages: []
    backends: [cpu]
""")
        registry = load_registry(p)
        assert registry["lazy_no_repo"].runtime == BundleRuntime.LAZY

    def test_builtin_defaults_have_runtime(self) -> None:
        defaults = _builtin_defaults()
        assert defaults["whisperx"].runtime == BundleRuntime.LAZY
        assert defaults["minicpm_v2_6"].runtime == BundleRuntime.TRANSFORMERS
        assert "image_review" in defaults["minicpm_v2_6"].capabilities


# ── Manifest v2 round-trip ────────────────────────────────────────────────────

class TestManifestV2:
    def test_save_and_load_new_fields(self, tmp_path: Path) -> None:
        state = ModelState(
            name="test_model",
            status=ModelStatus.VERIFIED,
            backend="cuda",
            cache_path="/cache/test",
            capabilities=["image_review", "structured_json"],
            checksum_verified=True,
            warm_inference_ok=False,
            bundle_artifacts={"text_model": "/cache/test/model.gguf"},
            failure_reason="",
        )
        save_manifest(tmp_path, {"test_model": state})

        loaded = load_manifest(tmp_path)
        assert "test_model" in loaded
        s = loaded["test_model"]
        assert s.capabilities == ["image_review", "structured_json"]
        assert s.checksum_verified is True
        assert s.warm_inference_ok is False
        assert s.bundle_artifacts == {"text_model": "/cache/test/model.gguf"}
        assert s.failure_reason == ""

    def test_schema_version_2_written(self, tmp_path: Path) -> None:
        save_manifest(tmp_path, {"m": ModelState(name="m", status=ModelStatus.VERIFIED)})
        manifest_path = tmp_path / "models" / "model-manifest.json"
        raw = json.loads(manifest_path.read_text())
        assert raw.get("schema_version") == "2"

    def test_old_manifest_loads_without_new_fields(self, tmp_path: Path) -> None:
        """Legacy manifests without bundle fields load with safe defaults."""
        manifest_path = tmp_path / "models" / "model-manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps({
            "schema_version": "1",
            "models": {
                "old_model": {
                    "status": "verified",
                    "backend": "cpu",
                    "cache_path": "/cache",
                    "revision": "",
                    "error": "",
                    "packages_ok": True,
                }
            }
        }))
        loaded = load_manifest(tmp_path)
        s = loaded["old_model"]
        assert s.capabilities == []
        assert s.checksum_verified is False
        assert s.bundle_artifacts == {}
        assert s.failure_reason == ""


# ── LocalAIModelManager.validate_capabilities ─────────────────────────────────

class TestManagerValidateCapabilities:
    def _make_manager(self, tmp_path: Path, registry_yaml: str):
        from ytfactory.models import LocalAIModelManager
        reg = tmp_path / "registry.yaml"
        reg.write_text(registry_yaml)
        return LocalAIModelManager(base_dir=tmp_path, registry_path=reg)

    def test_all_satisfied_returns_empty(self, tmp_path: Path) -> None:
        from ytfactory.models import LocalAIModelManager
        manager = self._make_manager(tmp_path, """
models:
  vision_m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/vm"
    description: "Vision"
    requires_packages: []
    backends: [cpu]
    runtime: transformers
    capabilities: [image_review, structured_json]
""")
        missing = manager.validate_capabilities("vision_m", ["image_review"])
        assert missing == []

    def test_missing_capability_returned(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/m"
    description: "M"
    requires_packages: []
    backends: [cpu]
    runtime: transformers
    capabilities: [structured_json]
""")
        missing = manager.validate_capabilities("m", ["image_review", "structured_json"])
        assert missing == ["image_review"]

    def test_unknown_model_returns_all_required_as_missing(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, "models: {}")
        missing = manager.validate_capabilities("no_such_model", ["image_review"])
        assert "image_review" in missing

    def test_empty_required_always_passes(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: ""
    requires_packages: []
    backends: [cpu]
""")
        assert manager.validate_capabilities("m", []) == []


# ── LocalAIModelManager.get_bundle ────────────────────────────────────────────

class TestManagerGetBundle:
    def _make_manager(self, tmp_path: Path, registry_yaml: str):
        from ytfactory.models import LocalAIModelManager
        reg = tmp_path / "registry.yaml"
        reg.write_text(registry_yaml)
        return LocalAIModelManager(base_dir=tmp_path, registry_path=reg)

    def test_returns_bundle_for_known_model(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: "org/m"
    description: "M"
    requires_packages: []
    backends: [cpu]
    runtime: transformers
    capabilities: []
""")
        bundle = manager.get_bundle("m")
        assert bundle is not None
        assert isinstance(bundle, ModelBundle)

    def test_returns_none_for_unknown_model(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, "models: {}")
        assert manager.get_bundle("nonexistent") is None

    def test_lazy_bundle_runtime(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  lazy_m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "Lazy"
    requires_packages: []
    backends: [cpu]
    runtime: lazy
    capabilities: []
""")
        bundle = manager.get_bundle("lazy_m")
        assert bundle is not None
        assert bundle.runtime == BundleRuntime.LAZY


# ── LocalAIModelManager.provision — bundle routing ────────────────────────────

class TestManagerProvisionBundleRouting:
    def _make_manager(self, tmp_path: Path, registry_yaml: str):
        from ytfactory.models import LocalAIModelManager
        reg = tmp_path / "registry.yaml"
        reg.write_text(registry_yaml)
        return LocalAIModelManager(base_dir=tmp_path, registry_path=reg)

    def test_lazy_model_verified_without_download(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  lazy_m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "Lazy"
    requires_packages: []
    backends: [cpu]
    runtime: lazy
    capabilities: []
""")
        result = manager.provision("lazy_m")
        assert result.ok

    def test_disabled_model_skipped(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  m:
    enabled: false
    required: false
    auto_download: false
    hf_repo: "org/m"
    description: "M"
    requires_packages: []
    backends: [cpu]
""")
        result = manager.provision("m")
        assert result.status == ModelStatus.SKIPPED
        assert result.skipped is True

    def test_unknown_model_returns_error(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, "models: {}")
        result = manager.provision("no_such")
        assert result.status == ModelStatus.ERROR

    def test_capabilities_propagated_in_result(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  caps_m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "Lazy with caps"
    requires_packages: []
    backends: [cpu]
    runtime: lazy
    capabilities: [image_review, structured_json]
""")
        result = manager.provision("caps_m")
        assert result.ok
        assert "image_review" in result.capabilities

    def test_provision_records_capabilities_in_manifest(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  caps_m2:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "Lazy"
    requires_packages: []
    backends: [cpu]
    runtime: lazy
    capabilities: [image_review]
""")
        manager.provision("caps_m2")
        state = manager.status("caps_m2")
        assert "image_review" in state.capabilities

    def test_diagnostics_includes_runtime_and_capabilities(self, tmp_path: Path) -> None:
        manager = self._make_manager(tmp_path, """
models:
  diag_m:
    enabled: true
    required: false
    auto_download: false
    hf_repo: ""
    description: "Diag model"
    requires_packages: []
    backends: [cpu]
    runtime: lazy
    capabilities: [cap_a]
""")
        report = manager.diagnostics()
        entry = next(e for e in report if e["name"] == "diag_m")
        assert entry["runtime"] == "lazy"
        assert "cap_a" in entry["capabilities"]


# ── Default registry: new fields present ─────────────────────────────────────

class TestDefaultRegistry:
    def test_default_registry_has_runtime_fields(self) -> None:
        registry = load_registry()
        if not registry:
            pytest.skip("PyYAML not available")
        if "minicpm_v2_6" in registry:
            entry = registry["minicpm_v2_6"]
            assert entry.runtime == BundleRuntime.TRANSFORMERS
            assert "image_review" in entry.capabilities
        if "whisperx" in registry:
            assert registry["whisperx"].runtime == BundleRuntime.LAZY
        if "silero_vad" in registry:
            assert registry["silero_vad"].runtime == BundleRuntime.LAZY
