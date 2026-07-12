"""Model Registry — loads model definitions from YAML config.

Bundle Architecture extension
------------------------------
Each registry entry may now declare:

  runtime:        lazy | transformers | llama_cpp
  capabilities:   [image_review, structured_json, ...]
  bundle:
    artifacts:
      <name>:
        file:     filename or "." for whole-repo snapshot
        revision: null | <sha>
        checksum: null | "sha256:<hex>"
        compatible_with: [...]
    warm_inference:
      sample_image:  "bundled://..." | path
      sample_prompt: "Describe this image."

Entries without these fields are treated as legacy Transformers entries
and behave exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from .models import (
    BundleArtifact,
    BundleRuntime,
    ModelBundle,
    ModelEntry,
    WarmInferenceConfig,
)

_DEFAULT_REGISTRY = Path(__file__).parent.parent.parent.parent / "config" / "models-registry.yaml"


def load_registry(registry_path: Path | None = None) -> dict[str, ModelEntry]:
    """Load model entries from the YAML registry file."""
    path = registry_path or _DEFAULT_REGISTRY
    if not path.exists():
        return {}

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return _builtin_defaults()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

    entries: dict[str, ModelEntry] = {}
    for name, cfg in (raw.get("models") or {}).items():
        if not isinstance(cfg, dict):
            continue
        entries[name] = _parse_entry(name, cfg)
    return entries


# ── Entry parsing ──────────────────────────────────────────────────────────────

def _parse_entry(name: str, cfg: dict) -> ModelEntry:
    hf_repo = str(cfg.get("hf_repo", ""))

    # Runtime — infer from hf_repo when not explicitly set
    raw_runtime = cfg.get("runtime", "")
    if raw_runtime:
        try:
            runtime = BundleRuntime(raw_runtime)
        except ValueError:
            runtime = BundleRuntime.LAZY if not hf_repo else BundleRuntime.TRANSFORMERS
    else:
        runtime = BundleRuntime.LAZY if not hf_repo else BundleRuntime.TRANSFORMERS

    capabilities: list[str] = list(cfg.get("capabilities") or [])
    bundle = _parse_bundle(cfg, runtime, capabilities)

    return ModelEntry(
        name=name,
        enabled=bool(cfg.get("enabled", True)),
        required=bool(cfg.get("required", False)),
        auto_download=bool(cfg.get("auto_download", False)),
        hf_repo=hf_repo,
        description=str(cfg.get("description", "")),
        requires_packages=list(cfg.get("requires_packages") or []),
        backends=list(cfg.get("backends") or ["cuda", "mps", "cpu"]),
        revision=cfg.get("revision"),
        min_disk_gb=float(cfg.get("min_disk_gb", 0.0)),
        warmup_on_download=bool(cfg.get("warmup_on_download", False)),
        capabilities=capabilities,
        runtime=runtime,
        bundle=bundle,
    )


def _parse_bundle(
    cfg: dict,
    runtime: BundleRuntime,
    capabilities: list[str],
) -> ModelBundle | None:
    """Parse the ``bundle:`` section of a registry entry.

    When no ``bundle:`` key is present a minimal synthetic bundle is created
    so that upper layers can always rely on ``entry.bundle`` being non-None.
    """
    bundle_cfg = cfg.get("bundle")
    artifacts: dict[str, BundleArtifact] = {}

    if isinstance(bundle_cfg, dict):
        artifacts_cfg = bundle_cfg.get("artifacts") or {}
        for art_name, art_cfg in artifacts_cfg.items():
            if not isinstance(art_cfg, dict):
                continue
            artifacts[art_name] = BundleArtifact(
                name=art_name,
                file=str(art_cfg.get("file", ".")),
                revision=art_cfg.get("revision"),
                checksum=art_cfg.get("checksum"),
                compatible_with=list(art_cfg.get("compatible_with") or []),
            )

        warm_cfg = bundle_cfg.get("warm_inference")
        warm: WarmInferenceConfig | None = None
        if isinstance(warm_cfg, dict):
            warm = WarmInferenceConfig(
                sample_image=str(warm_cfg.get("sample_image", "")),
                sample_prompt=str(warm_cfg.get("sample_prompt", "Describe this image.")),
            )

        return ModelBundle(
            runtime=runtime,
            artifacts=artifacts,
            capabilities=capabilities,
            warm_inference=warm,
            auto_validate=bool(bundle_cfg.get("auto_validate", False)),
            chat_format=str(bundle_cfg.get("chat_format", "")),
        )

    # Synthetic minimal bundle when no explicit bundle section
    hf_repo = cfg.get("hf_repo", "")
    if hf_repo:
        artifacts["text_model"] = BundleArtifact(name="text_model", file=".")
    return ModelBundle(
        runtime=runtime,
        artifacts=artifacts,
        capabilities=capabilities,
    )


# ── Builtin defaults (when PyYAML absent) ─────────────────────────────────────

def _builtin_defaults() -> dict[str, ModelEntry]:
    """Minimal hard-coded defaults when PyYAML is absent."""
    return {
        "whisperx": ModelEntry(
            name="whisperx",
            enabled=True,
            required=False,
            auto_download=False,
            hf_repo="",
            description="WhisperX forced alignment",
            requires_packages=["whisperx"],
            runtime=BundleRuntime.LAZY,
            capabilities=[],
        ),
        "silero_vad": ModelEntry(
            name="silero_vad",
            enabled=True,
            required=False,
            auto_download=False,
            hf_repo="",
            description="Silero VAD (voice activity detection)",
            requires_packages=[],
            backends=["cpu", "cuda"],
            runtime=BundleRuntime.LAZY,
            capabilities=[],
        ),
        "minicpm_v2_6": ModelEntry(
            name="minicpm_v2_6",
            enabled=True,
            required=False,
            auto_download=False,
            hf_repo="openbmb/MiniCPM-V-2_6",
            description="MiniCPM-V 2.6 vision model",
            requires_packages=["torch", "transformers", "pillow"],
            runtime=BundleRuntime.TRANSFORMERS,
            capabilities=["image_review", "structured_json"],
        ),
    }
