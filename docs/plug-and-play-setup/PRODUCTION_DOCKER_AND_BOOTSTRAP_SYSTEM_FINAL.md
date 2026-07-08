# PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM

> **Implementation Specification for Claude Code**
>
> **Read First:** `MASTER_CONTEXT_V4.md`
>
> **Mission:** Transform YouTube Factory into a production-grade,
> plug-and-play application that can be cloned onto a completely fresh
> machine and behave identically to the current development environment
> with minimal manual setup.

------------------------------------------------------------------------

# Vision

The current development machine is the **source of truth**.

A new machine should require only:

``` bash
git clone <repo>
cd youtube-factory
cp .env.example .env
# Add API keys

docker compose up -d

docker exec youtube-factory ytfactory setup
docker exec youtube-factory ytfactory doctor

docker exec youtube-factory     ytfactory build workspace/jobs/demo
```

Everything else must happen automatically.

------------------------------------------------------------------------

# Design Principles

-   Extend the existing architecture.
-   Never redesign working systems.
-   Preserve backward compatibility.
-   Reuse existing providers, factories, repositories, pipelines,
    validators, ReviewPipeline, AutoRemediation and Incremental Build
    Engine.
-   Eliminate hidden setup steps.
-   Bootstrap must be **idempotent**.
-   Prefer automatic repair over manual intervention.
-   Keep changes localized.
-   Build for local development, CI/CD and production.

------------------------------------------------------------------------

# Target Architecture

``` text
Git Clone
      │
Docker Compose
      │
Container Startup
      │
Bootstrap Engine
      ├── Environment Validation
      ├── Workspace Bootstrap
      ├── Configuration Validation
      ├── Provider Validation
      ├── Model Bootstrap
      ├── Cache Warmup
      ├── Self-Healing
      ├── Version Validation
      ├── Environment Report
      └── Bootstrap Manifest
      │
Ready
      │
ytfactory build
```

------------------------------------------------------------------------

# Docker Strategy

## Bake into the Image

-   Python
-   uv
-   Project source
-   Python dependencies
-   FFmpeg
-   Git
-   ImageMagick (if required)
-   Runtime libraries
-   CLI

## Do NOT Bake

-   WhisperX models
-   Silero VAD models
-   HuggingFace cache
-   Torch cache
-   Workspace
-   Logs
-   Temporary files
-   Downloadable fonts

These should be downloaded on first run and cached.

------------------------------------------------------------------------

# Docker Volumes

Persist:

-   workspace/
-   cache/
-   models/
-   logs/

Rebuilding the image must never lose downloaded models or caches.

------------------------------------------------------------------------

# Bootstrap Engine

Implement a dedicated Bootstrap Engine responsible for preparing the
entire environment.

## Environment Validation

Verify:

-   Python
-   FFmpeg
-   Git
-   Torch
-   CUDA
-   GPU
-   ONNX Runtime
-   Fonts
-   Shared libraries

Attempt automatic repair whenever possible.

------------------------------------------------------------------------

## Workspace Bootstrap

Automatically create and validate:

-   workspace/
-   cache/
-   models/
-   logs/
-   debug/
-   assets/
-   music/
-   temp/

Never require manual directory creation.

------------------------------------------------------------------------

## Configuration Bootstrap

Validate:

-   .env
-   Settings
-   Provider configuration
-   Model configuration
-   Workspace paths

Perform configuration migration when needed.

Never silently fall back to different defaults.

------------------------------------------------------------------------

## Provider Validation

Validate every configured provider:

-   Gemini
-   Anthropic
-   Tavily
-   Hugging Face
-   Groq
-   Kokoro
-   WhisperX
-   Future providers

Check:

-   API keys
-   Connectivity
-   Model availability
-   Permissions
-   Compatibility

Generate useful diagnostics.

------------------------------------------------------------------------

## Model Bootstrap

Automatically download missing models.

Examples:

-   WhisperX
-   Silero VAD
-   Future local models

Requirements:

-   Download once
-   Cache permanently
-   Reuse existing downloads
-   Never redownload unnecessarily

------------------------------------------------------------------------

## Cache Warmup

Warm caches for:

-   Torch
-   Whisper
-   ONNX
-   Fonts

Reduce first-build latency.

------------------------------------------------------------------------

# Self-Healing Engine

Automatically detect and repair:

-   Missing directories
-   Missing models
-   Corrupted cache
-   Missing fonts
-   Missing executables
-   Broken permissions
-   Broken symlinks

Repair automatically whenever safe.

Fail only when repair is impossible.

------------------------------------------------------------------------

# Version-Aware Bootstrap

Maintain:

bootstrap-manifest.json

Track:

-   Bootstrap version
-   Project version
-   Python version
-   Torch version
-   FFmpeg version
-   Provider versions
-   Model versions
-   Font versions
-   Validation timestamp

On startup:

-   Detect outdated models
-   Detect incompatible cache
-   Detect configuration changes
-   Perform migrations
-   Refresh only outdated assets

Avoid unnecessary downloads.

------------------------------------------------------------------------

# Production CLI

Implement or extend:

-   ytfactory setup
-   ytfactory doctor
-   ytfactory validate
-   ytfactory repair
-   ytfactory clean
-   ytfactory reset
-   ytfactory update
-   ytfactory version

All commands should be safe to run repeatedly.

------------------------------------------------------------------------

# Docker Profiles

Support:

-   CPU
-   NVIDIA GPU

Auto-detect capabilities where practical.

------------------------------------------------------------------------

# First Run Experience

Automatically:

-   Validate environment
-   Create workspace
-   Download models
-   Prepare fonts
-   Warm caches
-   Validate providers
-   Generate reports

Only API keys should require manual input.

------------------------------------------------------------------------

# Subsequent Runs

Reuse:

-   Models
-   Cache
-   Workspace
-   Reports

Skip completed work and become ready quickly.

------------------------------------------------------------------------

# Incremental Behaviour

-   Source changes → rebuild image
-   Configuration changes → validate only
-   Provider changes → revalidate provider
-   Model changes → download/update affected models only

------------------------------------------------------------------------

# Reports

Generate:

-   environment-report.json
-   bootstrap-manifest.json

Include:

-   Dependency versions
-   Provider status
-   Model status
-   Workspace status
-   Validation results
-   Compatibility status

------------------------------------------------------------------------

# CI/CD

The same Docker image should support:

-   Local development
-   GitHub Actions
-   Self-hosted runners
-   Production servers

Avoid environment-specific logic.

------------------------------------------------------------------------

# Documentation

Provide a complete installation guide covering:

-   Quick start
-   Docker
-   GPU support
-   Troubleshooting
-   Repair
-   Updates
-   Bootstrap workflow

------------------------------------------------------------------------

# Testing

Add automated tests for:

-   Bootstrap
-   Workspace creation
-   Configuration migration
-   Provider validation
-   Model downloads
-   Self-healing
-   Docker startup
-   CLI commands
-   Version migration

Run:

-   Ruff
-   MyPy
-   Full pytest suite

Everything must pass.

------------------------------------------------------------------------

# Deliverables

-   Dockerfile
-   docker-compose.yml
-   Bootstrap Engine
-   Workspace Bootstrap
-   Configuration Bootstrap
-   Provider Validator
-   Model Bootstrap
-   Cache Warmup
-   Self-Healing Engine
-   Version Manager
-   Bootstrap Manifest
-   Environment Report
-   Production CLI
-   Documentation
-   Tests

------------------------------------------------------------------------

# Success Criteria

A fresh machine should require only:

1.  Install Docker
2.  Clone repository
3.  Add API keys
4.  docker compose up -d
5.  ytfactory setup
6.  ytfactory doctor
7.  Build videos

The environment should automatically:

-   Install runtime dependencies
-   Download required models
-   Prepare workspace
-   Validate providers
-   Warm caches
-   Repair common issues
-   Produce the same output as the current development machine

No hidden setup. No manual dependency installation. No manual model
downloads. No environment-specific fixes.

During implementation, continuously improve the bootstrap experience
where appropriate, while preserving the existing architecture and
backward compatibility. Do not pause for approval; implement the best
production-quality solution.

------------------------------------------------------------------------

# Implementation Philosophy

Treat this work as building the **production platform** for YouTube
Factory, not merely adding Docker support.

The bootstrap system should follow these principles:

## Idempotent

Every bootstrap command (for example, `ytfactory setup`) must be safe to
execute repeatedly.

Running the same command multiple times should:

-   Skip work that has already been completed.
-   Never corrupt the environment.
-   Never duplicate downloads.
-   Never overwrite valid configuration unless explicitly requested.

## Self-Healing

Whenever possible, detect and automatically repair common problems
instead of failing immediately.

Examples include:

-   Missing directories
-   Missing models
-   Missing caches
-   Corrupted caches
-   Missing fonts
-   Broken permissions
-   Invalid symbolic links
-   Missing executables

Only stop with an error when automatic recovery is impossible.

## Version-Aware

The bootstrap process should understand versions of:

-   Project
-   Bootstrap
-   Python
-   Providers
-   AI models
-   Fonts
-   Runtime dependencies

On startup, intelligently:

-   Detect outdated assets
-   Migrate configuration
-   Refresh only what is necessary
-   Preserve existing caches whenever compatible

Avoid unnecessary downloads or rebuilding.

## Observable

The bootstrap process should always leave behind useful diagnostics.

Generate reports such as:

-   `environment-report.json`
-   `bootstrap-manifest.json`

These reports should make troubleshooting straightforward and clearly
describe:

-   Environment status
-   Installed components
-   Provider health
-   Model versions
-   Dependency versions
-   Validation results
-   Compatibility issues
-   Automatic repairs performed

The objective is that any developer should be able to understand the
system state without manually investigating the environment.
