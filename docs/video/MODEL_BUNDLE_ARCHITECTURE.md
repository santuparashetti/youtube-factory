# MODEL_BUNDLE_ARCHITECTURE.md

> **Implementation Specification for Claude Code**

## Objective

This document defines the architecture and implementation requirements for the **Model Bundle** system managed by the **Local AI Model Manager**.

Treat this document as the authoritative implementation specification.

Implement this architecture by extending the existing codebase.

Preserve backward compatibility.

Do **not** redesign or replace working systems.

Reuse the existing Bootstrap Engine, Provider abstraction, configuration system, workspace, Docker integration and Incremental Build Engine wherever possible.

The implementation should become the default architecture for all current and future local AI models.

---

# Model Bundle Architecture

## Objective

The Local AI Model Manager must treat every model as a **Model Bundle**, not as a single model file.

ReviewPipeline, Provider implementations and feature pipelines request only a logical model.

The Local AI Model Manager owns the lifecycle of every artifact required by that model.

---

## Model Bundle

A Model Bundle may contain one or more artifacts depending on the selected runtime.

Examples:

- Text model
- Vision projector (mmproj)
- Tokenizer
- Processor
- Configuration
- Runtime metadata
- Backend-specific auxiliary files

Feature implementations never download or manage these artifacts.

---

## Capability Contract

Providers declare capabilities in the registry.

Examples:

- image_review
- image_captioning
- structured_json
- streaming
- batch_inference

Consumers declare required capabilities.

The Local AI Model Manager validates that the selected provider satisfies those capabilities before returning a READY bundle.

Capability validation is registry-driven, not runtime probing.

Missing capabilities must return:

`MISSING_CAPABILITY(capability_name)`

---

## Runtime-aware Provisioning

Support runtime-specific bundle layouts.

### GGUF / llama.cpp

Provision automatically:

- GGUF model
- Matching mmproj
- Metadata

Example:

```yaml
bundle:
  text_model:
    file: Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf
    revision: <commit_sha>
    checksum: sha256:...

  vision_projector:
    file: mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf
    revision: <commit_sha>
    checksum: sha256:...
    compatible_with:
      - Qwen2.5-VL-3B-Instruct
```

### Hugging Face Transformers

Provision automatically:

- Model weights
- Processor
- Tokenizer
- Config

Future runtimes (vLLM, ONNX, TensorRT, etc.) should require only a new runtime adapter.

---

## Model Registry

The registry is configuration-driven.

Artifacts are pinned to explicit revisions.

Never resolve to "latest".

Revision changes are the only trigger for downloads.

Example:

```yaml
models:
  vision_review:
    provider: qwen2_5_vl
    runtime: llama_cpp
    capabilities:
      - image_review
      - structured_json

    bundle:
      text_model:
        file: Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf
        revision: <commit_sha>

      vision_projector:
        file: mmproj-Qwen2.5-VL-3B-Instruct-f16.gguf
        revision: <commit_sha>

    warm_inference:
      sample_image: bundled://assets/warmup/sample.jpg
      sample_prompt: "Describe this image."

    auto_download: true
    auto_validate: true
```

---

## Bootstrap Responsibilities

During `ytfactory setup` the Local AI Model Manager must:

- Discover required bundle artifacts.
- Download only missing artifacts.
- Resume interrupted downloads.
- Verify checksums when available.
- Fall back to file-size + successful load if checksums are unavailable and record `checksum_verified: false`.
- Validate bundle compatibility.
- Validate required capabilities.
- Cache artifacts using a content-addressed store.
- Support LRU eviction.
- Warm the model using the configured warm-up asset.
- Generate `models-manifest.json`.
- Acquire per-bundle locks to prevent duplicate provisioning.
- Mark READY only after successful validation.

No manual downloads.

---

## Validation

Validation must verify:

- Bundle artifacts exist.
- Components are compatible.
- Required capabilities are satisfied.
- Runtime loads.
- Warm inference succeeds.
- Provider initializes.
- Memory requirements are met.

---

## Models Manifest

The manifest records:

- provider
- runtime
- revision
- bundle artifacts
- checksum verification
- capabilities
- validation status
- READY state
- warm inference status

---

## Self-Healing

Repair only affected artifacts when:

- missing
- corrupted
- incompatible
- partially downloaded
- outdated

Then revalidate the complete bundle.

---

## Failure Contract

Return runtime-agnostic reasons:

- DOWNLOAD_FAILED
- DISK_FULL
- CHECKSUM_MISMATCH
- INCOMPATIBLE_BUNDLE
- MISSING_CAPABILITY
- VALIDATION_TIMEOUT

---

## Design Rule

```text
ReviewPipeline
      │
      ▼
Vision Provider
      │
      ▼
Local AI Model Manager
      │
      ▼
Model Bundle
```

Upper layers must never know whether a runtime requires mmproj, tokenizer, processor or any other auxiliary artifacts.

---

## Success Criteria

Changing models or runtimes requires configuration changes only.

The Local AI Model Manager automatically provisions, validates, repairs and exposes READY Model Bundles with zero manual setup.

---

# Implementation Requirements

During implementation:

- Extend the existing architecture.
- Preserve backward compatibility.
- Do not break the current working system.
- Reuse existing Bootstrap Engine, Provider abstraction, configuration system, Docker setup and Incremental Build Engine.
- Do not duplicate model download logic.
- Route every local model lifecycle operation through the Local AI Model Manager.
- Migrate existing pipelines without changing their public interfaces.
- Add unit and integration tests.
- Run Ruff, MyPy and the full test suite.
- Update documentation if setup or bootstrap behaviour changes.

Do not pause for approval.

Continue until the implementation is production-ready.
