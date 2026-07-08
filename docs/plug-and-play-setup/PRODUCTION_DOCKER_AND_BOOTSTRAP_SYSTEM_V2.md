# PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM_V2

> **Implementation Specification for Claude Code**
>
> Read `MASTER_CONTEXT_V4.md` before implementation.
>
> This is a production-hardening task. Extend the existing architecture.
> Do **not** redesign it.

# Vision

A brand-new machine should produce the **exact same output** as the
current development machine.

The project should behave like a professional developer tool.

``` bash
git clone <repo>
cd youtube-factory
cp .env.example .env   # Add API keys
docker compose up -d
docker exec youtube-factory ytfactory setup
docker exec youtube-factory ytfactory build workspace/jobs/demo
```

No hidden setup. No manual dependency installation. No manual model
downloads. No manual directory creation.

------------------------------------------------------------------------

# Design Principles

-   Reuse existing architecture.
-   Preserve backward compatibility.
-   Keep changes localized.
-   Configuration drives behaviour.
-   Bootstrap is idempotent.
-   Self-heal whenever possible.
-   Prefer automation over documentation.
-   Minimize image size while maximizing reproducibility.

------------------------------------------------------------------------

# Runtime Architecture

Docker Image - Python - uv - Project source - Python dependencies -
FFmpeg - Git - ImageMagick (if used) - Runtime libraries - CLI

Persistent Volumes - workspace/ - cache/ - models/ - logs/

Downloaded On First Run - WhisperX models - Silero VAD - Torch caches -
HuggingFace cache - Downloadable fonts - Future local AI models

Never redownload unchanged assets.

------------------------------------------------------------------------

# Bootstrap Engine

Implement a dedicated Bootstrap Engine executed by:

-   ytfactory setup
-   container startup (light validation)
-   repair (partial)
-   update (migration)

Responsibilities

1.  Validate environment
2.  Create required folders
3.  Validate configuration
4.  Validate providers
5.  Download missing models
6.  Prepare fonts
7.  Warm caches
8.  Generate reports
9.  Perform safe repairs

Bootstrap must be repeatable without side effects.

------------------------------------------------------------------------

# Bootstrap Manifest

Maintain:

bootstrap-manifest.json

Track:

-   bootstrap version
-   project version
-   python version
-   ffmpeg version
-   torch version
-   cuda version
-   installed models
-   downloaded fonts
-   provider validation status
-   workspace schema version
-   last validation timestamp

Use this manifest to decide whether migrations, downloads or cache
refreshes are required.

------------------------------------------------------------------------

# Environment Validation

Verify:

-   Python
-   FFmpeg
-   Git
-   CUDA
-   GPU
-   Torch
-   ONNX Runtime
-   Fonts
-   ImageMagick
-   System libraries

Provide actionable diagnostics.

------------------------------------------------------------------------

# Provider Validation

Validate every enabled provider.

Check:

-   API key
-   connectivity
-   configured model
-   permissions
-   compatibility

Cache validation results where appropriate.

------------------------------------------------------------------------

# Workspace Bootstrap

Automatically create and validate:

workspace/ cache/ models/ logs/ music/ assets/ debug/ temp/

Repair if missing.

------------------------------------------------------------------------

# Model Manager

Automatically install and cache:

-   WhisperX
-   Silero VAD
-   Future local models

Capabilities:

-   version-aware
-   resumable downloads
-   checksum verification
-   retry with backoff
-   no duplicate downloads

------------------------------------------------------------------------

# Self-Healing

Automatically repair:

-   missing directories
-   missing models
-   corrupted cache
-   missing fonts
-   invalid permissions
-   broken symlinks
-   outdated manifest
-   partially completed downloads

Only request user intervention when repair is impossible.

------------------------------------------------------------------------

# Docker Profiles

Support:

-   CPU
-   GPU

GPU profile should automatically use NVIDIA runtime when available.

CPU remains the default.

------------------------------------------------------------------------

# CLI

Implement or extend:

ytfactory setup ytfactory doctor ytfactory validate ytfactory repair
ytfactory clean ytfactory reset ytfactory update ytfactory version

Each command should have concise output and machine-readable JSON mode
where practical.

------------------------------------------------------------------------

# Logging & Reports

Generate:

environment-report.json bootstrap-report.json

Include versions, providers, models, validation results, repair actions
and timings.

------------------------------------------------------------------------

# Upgrade Strategy

Project upgrades should:

-   migrate configuration
-   migrate workspace schema
-   preserve user assets
-   preserve downloaded models
-   preserve caches where compatible
-   invalidate only what is necessary

------------------------------------------------------------------------

# Incremental Behaviour

Code change: - rebuild image

Configuration change: - reload configuration only

Model change: - update affected model

Provider change: - revalidate provider only

Avoid unnecessary work.

------------------------------------------------------------------------

# CI/CD

Ensure the Docker image can be built in CI.

Add automated smoke tests:

-   image builds
-   setup succeeds
-   doctor succeeds
-   demo build completes

------------------------------------------------------------------------

# Documentation

Rewrite installation guide for a new machine.

Document only the supported workflow.

Eliminate undocumented manual steps.

------------------------------------------------------------------------

# Deliverables

-   Dockerfile
-   docker-compose.yml
-   Bootstrap Engine
-   Model Manager
-   Provider Validator
-   Workspace Bootstrap
-   Self-Healing Engine
-   Bootstrap Manifest
-   Installation scripts
-   Production CLI
-   Updated documentation
-   Automated tests

------------------------------------------------------------------------

# Success Criteria

A new developer should only need:

1.  Install Docker
2.  Clone repository
3.  Add API keys
4.  docker compose up -d
5.  ytfactory setup
6.  ytfactory build

Everything else should be automated.

If any prerequisite is missing, the system should detect it, repair it
when safe, or provide a precise remediation message.

At completion, provide: - implementation summary - modified files - new
files - configuration changes - validation results - remaining manual
requirements (if any)
