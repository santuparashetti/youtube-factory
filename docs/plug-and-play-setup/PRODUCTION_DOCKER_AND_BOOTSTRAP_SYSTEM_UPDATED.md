# PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM

> **Implementation Specification for Claude Code**

Read `MASTER_CONTEXT.md` before implementation.

## Mission

Transform YouTube Factory into a production-grade, plug-and-play application.

This document is the single source of truth for:

- Docker
- Bootstrap Engine
- Local AI Model Manager
- Environment validation
- Workspace provisioning
- Local AI model lifecycle
- Self-healing
- Production CLI

Feature specifications must reuse this platform instead of implementing their own bootstrap logic.

---

## Local AI Model Manager

The **Local AI Model Manager** is a core platform component.

No feature (Image Review, WhisperX, OCR, etc.) may download or manage local models directly.

All local model lifecycle operations must go through this manager.

### Responsibilities

- Discover required models
- Download missing models
- Resume interrupted downloads
- Verify checksums
- Validate model integrity
- Cache models
- Warm models
- Upgrade outdated models
- Roll back invalid upgrades
- Select backend (CUDA → MPS → CPU)
- Repair corrupted models
- Remove invalid caches
- Update manifests
- Generate diagnostics

---

## Supported Models

Initially:

- WhisperX
- Silero VAD
- MiniCPM-V 2.6 (default vision reviewer)

Future:

- Qwen2.5-VL
- OCR
- Face Detection
- Scene Classification
- Music Classification
- Image Upscalers

Adding a model should require configuration only.

---

## Model Registry

```yaml
models:
  whisperx:
    enabled: true
    required: true
    auto_download: true

  silero_vad:
    enabled: true
    required: true
    auto_download: true

  vision:
    enabled: true
    provider: local
    model: minicpm_v2_6
    auto_download: true
```

---

## Bootstrap

`ytfactory setup` should:

1. Validate environment
2. Create workspace
3. Validate configuration
4. Read model registry
5. Provision required models through the Local AI Model Manager
6. Warm caches
7. Validate providers
8. Generate reports

The bootstrap must be idempotent.

---

## Docker

Bake:

- Python
- uv
- FFmpeg
- dependencies
- project source

Do not bake:

- models
- caches
- workspace
- logs

Persist:

- models/
- cache/
- workspace/
- logs/

---

## Rules

- Bootstrap prepares the environment.
- Local AI Model Manager owns every local model.
- Pipelines use provider abstractions only.
- Never duplicate download logic.
- Preserve backward compatibility.
- Do not break the current working system.

---

## Success Criteria

Fresh machine:

1. Install Docker
2. Clone repository
3. Configure API keys
4. docker compose up -d
5. ytfactory setup

Everything else—including provisioning WhisperX, Silero VAD, MiniCPM-V and future local models—must happen automatically.

No manual model downloads.
No manual Hugging Face setup.
No manual wiring.
