"""Data models for the Local AI Model Manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ModelStatus(str, Enum):
    UNKNOWN = "unknown"
    MISSING = "missing"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    VERIFIED = "verified"
    CORRUPTED = "corrupted"
    SKIPPED = "skipped"
    ERROR = "error"


class Backend(str, Enum):
    CUDA = "cuda"
    MPS = "mps"
    CPU = "cpu"


class BundleRuntime(str, Enum):
    """Runtime used to load and serve the model."""

    TRANSFORMERS = "transformers"   # HuggingFace Transformers (snapshot_download)
    LLAMA_CPP = "llama_cpp"         # GGUF quantised via llama.cpp
    LAZY = "lazy"                   # no managed download — library handles internally


class FailureReason(str, Enum):
    """Runtime-agnostic failure contract returned by the provisioning pipeline."""

    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    DISK_FULL = "DISK_FULL"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    INCOMPATIBLE_BUNDLE = "INCOMPATIBLE_BUNDLE"
    MISSING_CAPABILITY = "MISSING_CAPABILITY"
    VALIDATION_TIMEOUT = "VALIDATION_TIMEOUT"


@dataclass
class BundleArtifact:
    """A single artifact within a Model Bundle.

    For GGUF bundles: one entry per file (text_model, vision_projector, …).
    For Transformers bundles: typically one entry whose *file* is ``"."``
    (the whole HF snapshot directory).
    """

    name: str                                       # logical role: "text_model", "vision_projector"
    file: str                                       # filename in HF repo or GGUF filename
    revision: str | None = None                     # pinned commit SHA / tag
    checksum: str | None = None                     # "sha256:<hex>" — None ⇒ verify by presence
    compatible_with: list[str] = field(default_factory=list)


@dataclass
class WarmInferenceConfig:
    """Configuration for a warm-up inference pass executed after provisioning."""

    sample_image: str = ""                          # "bundled://..." or filesystem path
    sample_prompt: str = "Describe this image."


@dataclass
class ModelBundle:
    """A collection of artifacts that together form one logical model.

    Upper layers (ReviewPipeline, Provider) never know which specific
    artifact files are needed — that is entirely the bundle's concern.
    """

    runtime: BundleRuntime
    artifacts: dict[str, BundleArtifact]            # artifact_name → BundleArtifact
    capabilities: list[str] = field(default_factory=list)
    warm_inference: WarmInferenceConfig | None = None
    auto_validate: bool = False
    chat_format: str = ""                            # llama.cpp chat format (e.g. "qwen2_5-vl")


@dataclass
class ModelEntry:
    """Single entry from the model registry."""

    name: str
    enabled: bool
    required: bool
    auto_download: bool
    hf_repo: str
    description: str
    requires_packages: list[str] = field(default_factory=list)
    backends: list[str] = field(default_factory=lambda: ["cuda", "mps", "cpu"])
    revision: str | None = None
    min_disk_gb: float = 0.0
    warmup_on_download: bool = False
    # ── Model Bundle Architecture ─────────────────────────────────────────────
    capabilities: list[str] = field(default_factory=list)
    runtime: BundleRuntime = BundleRuntime.TRANSFORMERS
    bundle: ModelBundle | None = None


@dataclass
class ModelState:
    """Runtime state for a single model (written to the manifest)."""

    name: str
    status: ModelStatus = ModelStatus.UNKNOWN
    backend: str = "cpu"
    cache_path: str = ""
    revision: str = ""
    error: str = ""
    packages_ok: bool = False
    # ── Model Bundle Architecture ─────────────────────────────────────────────
    capabilities: list[str] = field(default_factory=list)
    checksum_verified: bool = False
    warm_inference_ok: bool = False
    bundle_artifacts: dict[str, str] = field(default_factory=dict)  # art_name → local path
    failure_reason: str = ""                        # FailureReason value when status == ERROR


@dataclass
class ProvisionResult:
    """Result of a provisioning operation for one model."""

    name: str
    status: ModelStatus
    backend: str = "cpu"
    message: str = ""
    error: str = ""
    skipped: bool = False
    # ── Model Bundle Architecture ─────────────────────────────────────────────
    failure_reason: str = ""                        # FailureReason value when status == ERROR
    capabilities: list[str] = field(default_factory=list)
    bundle_artifacts: dict[str, str] = field(default_factory=dict)
    checksum_verified: bool = False

    @property
    def ok(self) -> bool:
        return self.status in (ModelStatus.VERIFIED, ModelStatus.DOWNLOADED, ModelStatus.SKIPPED)
