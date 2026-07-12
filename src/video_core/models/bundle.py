"""Bundle provisioning — content-addressed artifact management with locking.

Handles per-artifact download, checksum verification, per-bundle locking,
LRU eviction, and warm-inference hooks for the Model Bundle architecture.

Design principles
-----------------
- One threading.Lock per bundle name — prevents concurrent duplicate provisioning.
- Content-addressed cache stores GGUF artifacts by sha256 checksum.
  Transformers bundles are managed by the HF hub cache (no duplication).
- LRU eviction metadata is maintained in ``{cache_dir}/.lru.json``.
- Checksum verification: ``sha256:<hex>`` format.  When no checksum is
  configured, presence + non-zero size is accepted and ``checksum_verified``
  is set to ``False`` in the manifest.
- All failure paths return a ``FailureReason`` string rather than raising.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

from loguru import logger

from .models import (
    BundleRuntime,
    FailureReason,
    ModelBundle,
    ModelStatus,
)


# ── Per-bundle in-process locking ─────────────────────────────────────────────

_BUNDLE_LOCKS: dict[str, threading.Lock] = {}
_LOCK_REGISTRY = threading.Lock()


def get_bundle_lock(name: str) -> threading.Lock:
    """Return (or create) the per-bundle in-process lock."""
    with _LOCK_REGISTRY:
        if name not in _BUNDLE_LOCKS:
            _BUNDLE_LOCKS[name] = threading.Lock()
        return _BUNDLE_LOCKS[name]


# ── Content-addressed artifact cache ──────────────────────────────────────────

class ContentAddressedCache:
    """Simple content-addressed artifact store.

    Artifacts are stored under:
        ``{cache_dir}/{prefix}/{checksum}/{filename}``

    where ``prefix`` is the first two characters of the checksum hex digest
    (git-object-store style), keeping the directory shallow.

    Access times are tracked in ``{cache_dir}/.lru.json`` to support
    LRU eviction.
    """

    _LRU_FILE = ".lru.json"

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, checksum_hex: str, filename: str) -> Path | None:
        """Return the cached artifact path if present and non-empty."""
        path = self._artifact_path(checksum_hex, filename)
        if path.exists() and path.stat().st_size > 0:
            self._touch_lru(checksum_hex)
            return path
        return None

    def put(self, checksum_hex: str, filename: str, source: Path) -> Path:
        """Copy *source* into the cache under *checksum_hex* and return stored path."""
        import shutil
        dest = self._artifact_path(checksum_hex, filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        self._touch_lru(checksum_hex)
        return dest

    def evict_lru(self, keep_n: int = 5) -> int:
        """Remove least-recently-used entries keeping at most *keep_n*. Returns count evicted."""
        import shutil
        lru = self._load_lru()
        if len(lru) <= keep_n:
            return 0
        sorted_entries = sorted(lru.items(), key=lambda kv: kv[1])
        to_evict = sorted_entries[: len(sorted_entries) - keep_n]
        evicted = 0
        for checksum_hex, _ in to_evict:
            prefix = checksum_hex[:2] if len(checksum_hex) >= 2 else "xx"
            entry_dir = self._dir / prefix / checksum_hex
            if entry_dir.exists():
                shutil.rmtree(entry_dir, ignore_errors=True)
                evicted += 1
            lru.pop(checksum_hex, None)
        self._save_lru(lru)
        return evicted

    # -- Internal helpers ------------------------------------------------------

    def _artifact_path(self, checksum_hex: str, filename: str) -> Path:
        prefix = checksum_hex[:2] if len(checksum_hex) >= 2 else "xx"
        return self._dir / prefix / checksum_hex / filename

    def _load_lru(self) -> dict[str, float]:
        path = self._dir / self._LRU_FILE
        try:
            return dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return {}

    def _save_lru(self, lru: dict[str, float]) -> None:
        path = self._dir / self._LRU_FILE
        try:
            path.write_text(json.dumps(lru, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _touch_lru(self, checksum_hex: str) -> None:
        lru = self._load_lru()
        lru[checksum_hex] = time.time()
        self._save_lru(lru)


# ── Checksum helpers ──────────────────────────────────────────────────────────

def compute_sha256(path: Path) -> str:
    """Return the sha256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_checksum(path: Path, expected: str) -> bool:
    """Verify *path* against an expected checksum string.

    Accepts ``"sha256:<hex>"`` format.  Returns ``True`` when checksum matches
    or when *expected* is empty/None (no verification configured).
    """
    if not expected:
        return True
    if not expected.startswith("sha256:"):
        logger.warning("Unsupported checksum format '{}' — accepting without verification", expected)
        return True
    expected_hex = expected[len("sha256:"):]
    actual = compute_sha256(path)
    if actual != expected_hex:
        logger.error(
            "Checksum mismatch for {}: expected {}… got {}…",
            path.name,
            expected_hex[:16],
            actual[:16],
        )
        return False
    return True


# ── Bundle provisioner ────────────────────────────────────────────────────────

class BundleProvisioner:
    """Provisions a Model Bundle — coordinates per-artifact download and verification.

    Supports runtimes:
    - ``LAZY``         — no managed download; returns VERIFIED immediately.
    - ``TRANSFORMERS`` — delegates to HuggingFace hub ``snapshot_download``.
    - ``LLAMA_CPP``    — downloads individual GGUF files; stores in content-addressed cache.

    Per-bundle in-process locking prevents concurrent duplicate provisioning.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._cache = ContentAddressedCache(base_dir / "models" / "artifacts")

    def provision(
        self,
        name: str,
        bundle: ModelBundle,
        hf_repo: str,
        revision: str | None,
        *,
        force: bool = False,
    ) -> tuple[ModelStatus, str, dict[str, str], bool]:
        """Provision a bundle under a per-bundle lock.

        Returns
        -------
        (status, message, artifact_paths, checksum_verified)
        """
        lock = get_bundle_lock(name)
        with lock:
            return self._provision_locked(name, bundle, hf_repo, revision, force=force)

    # -- Dispatch by runtime ---------------------------------------------------

    def _provision_locked(
        self,
        name: str,
        bundle: ModelBundle,
        hf_repo: str,
        revision: str | None,
        *,
        force: bool,
    ) -> tuple[ModelStatus, str, dict[str, str], bool]:
        runtime = bundle.runtime

        if runtime == BundleRuntime.LAZY:
            return ModelStatus.VERIFIED, "Lazy bundle — downloads on first use", {}, True

        if runtime == BundleRuntime.TRANSFORMERS:
            return self._provision_transformers(name, bundle, hf_repo, revision, force=force)

        if runtime == BundleRuntime.LLAMA_CPP:
            return self._provision_llama_cpp(name, bundle, hf_repo, revision, force=force)

        return (
            ModelStatus.ERROR,
            f"{FailureReason.INCOMPATIBLE_BUNDLE}: unknown runtime '{runtime}'",
            {},
            False,
        )

    # -- Transformers runtime --------------------------------------------------

    def _provision_transformers(
        self,
        name: str,
        bundle: ModelBundle,
        hf_repo: str,
        revision: str | None,
        *,
        force: bool,
    ) -> tuple[ModelStatus, str, dict[str, str], bool]:
        if not hf_repo:
            return ModelStatus.VERIFIED, "Lazy transformers model — no HF repo", {}, True

        try:
            from huggingface_hub import snapshot_download  # type: ignore[import-not-found]
        except ImportError:
            return (
                ModelStatus.ERROR,
                f"{FailureReason.DOWNLOAD_FAILED}: huggingface_hub not installed",
                {},
                False,
            )

        err = self._check_disk()
        if err:
            return ModelStatus.ERROR, err, {}, False

        try:
            cache_path = snapshot_download(
                repo_id=hf_repo,
                revision=revision,
                ignore_patterns=["*.msgpack", "flax_model*"],
                force_download=force,
            )
        except OSError as exc:
            if _is_disk_full(exc):
                return ModelStatus.ERROR, f"{FailureReason.DISK_FULL}: {exc}", {}, False
            return ModelStatus.ERROR, f"{FailureReason.DOWNLOAD_FAILED}: {exc}", {}, False
        except Exception as exc:
            return ModelStatus.ERROR, f"{FailureReason.DOWNLOAD_FAILED}: {exc}", {}, False

        # Verify individual artifacts (if checksum configured)
        artifact_paths: dict[str, str] = {}
        checksum_verified = True
        for art_name, artifact in bundle.artifacts.items():
            if artifact.file and artifact.file != ".":
                art_file = Path(cache_path) / artifact.file
                if art_file.exists() and artifact.checksum:
                    if not verify_checksum(art_file, artifact.checksum):
                        return (
                            ModelStatus.CORRUPTED,
                            f"{FailureReason.CHECKSUM_MISMATCH}: {artifact.file}",
                            {},
                            False,
                        )
                artifact_paths[art_name] = str(art_file) if art_file.exists() else str(cache_path)
            else:
                if artifact.checksum:
                    checksum_verified = False  # whole-repo snapshot has no single checksum
                artifact_paths[art_name] = str(cache_path)

        return ModelStatus.VERIFIED, f"Downloaded to {cache_path}", artifact_paths, checksum_verified

    # -- llama.cpp / GGUF runtime ---------------------------------------------

    def _provision_llama_cpp(
        self,
        name: str,
        bundle: ModelBundle,
        hf_repo: str,
        revision: str | None,
        *,
        force: bool,
    ) -> tuple[ModelStatus, str, dict[str, str], bool]:
        try:
            from huggingface_hub import hf_hub_download  # type: ignore[import-not-found]
        except ImportError:
            return (
                ModelStatus.ERROR,
                f"{FailureReason.DOWNLOAD_FAILED}: huggingface_hub not installed",
                {},
                False,
            )

        err = self._check_disk()
        if err:
            return ModelStatus.ERROR, err, {}, False

        artifact_paths: dict[str, str] = {}
        checksum_verified = True

        for art_name, artifact in bundle.artifacts.items():
            # Content-addressed cache look-up (skip when force=True)
            if artifact.checksum and not force:
                checksum_hex = artifact.checksum.replace("sha256:", "")
                cached = self._cache.get(checksum_hex, artifact.file)
                if cached is not None:
                    logger.debug(
                        "GGUF artifact '{}' found in content-addressed cache", artifact.file
                    )
                    artifact_paths[art_name] = str(cached)
                    continue

            # Download from HF hub
            try:
                local_path = hf_hub_download(
                    repo_id=hf_repo,
                    filename=artifact.file,
                    revision=artifact.revision or revision,
                    force_download=force,
                )
            except OSError as exc:
                if _is_disk_full(exc):
                    return ModelStatus.ERROR, f"{FailureReason.DISK_FULL}: {exc}", {}, False
                return (
                    ModelStatus.ERROR,
                    f"{FailureReason.DOWNLOAD_FAILED}: {artifact.file}: {exc}",
                    {},
                    False,
                )
            except Exception as exc:
                return (
                    ModelStatus.ERROR,
                    f"{FailureReason.DOWNLOAD_FAILED}: {artifact.file}: {exc}",
                    {},
                    False,
                )

            local = Path(local_path)

            # Checksum verification
            if artifact.checksum:
                if not verify_checksum(local, artifact.checksum):
                    return (
                        ModelStatus.CORRUPTED,
                        f"{FailureReason.CHECKSUM_MISMATCH}: {artifact.file}",
                        {},
                        False,
                    )
                checksum_hex = artifact.checksum.replace("sha256:", "")
                stored = self._cache.put(checksum_hex, artifact.file, local)
                artifact_paths[art_name] = str(stored)
            else:
                checksum_verified = False
                artifact_paths[art_name] = str(local)

        return (
            ModelStatus.VERIFIED,
            f"GGUF bundle ready ({list(artifact_paths.keys())})",
            artifact_paths,
            checksum_verified,
        )

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _check_disk() -> str:
        """Return a DISK_FULL error string if < 1 GB free; empty string otherwise."""
        try:
            stat = os.statvfs("/")
            free_gb = (stat.f_frsize * stat.f_bavail) / (1024 ** 3)
            if free_gb < 1.0:
                return f"{FailureReason.DISK_FULL}: only {free_gb:.1f} GB free"
        except (AttributeError, OSError):
            pass  # statvfs unavailable on Windows — skip check
        return ""


def _is_disk_full(exc: OSError) -> bool:
    msg = str(exc).lower()
    return "no space" in msg or "disk full" in msg or "enospc" in msg
