# PRODUCTION_DOCKER_AND_BOOTSTRAP_SYSTEM_V1.md

> **Implementation Specification for Claude Code**
>
> **Prerequisite:** Read `MASTER_CONTEXT.md` before implementation.
>
> **Purpose:** Convert YouTube Factory into a true production-ready,
> plug-and-play application that can be cloned and run on any supported
> machine with minimal manual setup.

------------------------------------------------------------------------

# Vision

The current development machine is the **source of truth**.

A freshly cloned repository should behave **identically** after setup.

The goal is:

``` bash
git clone <repo>

cd youtube-factory

cp .env.example .env
# Add API keys

docker compose up -d

docker exec youtube-factory ytfactory setup

docker exec youtube-factory ytfactory build workspace/jobs/demo
```

No hidden setup.

No manual dependency installation.

No manual directory creation.

No manual model downloads.

No environment-specific fixes.

------------------------------------------------------------------------

# Primary Objectives

-   Production-ready Docker environment
-   One-command bootstrap
-   Automatic dependency validation
-   Automatic model download
-   Automatic workspace preparation
-   Automatic repair of common issues
-   Environment reproducibility
-   Backward compatibility
-   Zero hidden manual steps

------------------------------------------------------------------------

# Non-Negotiable Rules

-   Do NOT redesign the project.
-   Reuse existing architecture.
-   Reuse providers, factories, pipelines and validators.
-   Preserve existing CLI.
-   Preserve incremental builds.
-   Preserve ReviewPipeline.
-   Preserve AutoRemediation.
-   Keep changes localized.

------------------------------------------------------------------------

# Overall Architecture

``` text
Git Clone
      │
      ▼
Docker Compose
      │
      ▼
Container Starts
      │
      ▼
Bootstrap Engine
      │
      ├── Validate Environment
      ├── Create Workspace
      ├── Validate Providers
      ├── Download Models
      ├── Prepare Fonts
      ├── Warm Caches
      ├── Generate Reports
      ▼
Ready
      │
      ▼
ytfactory build
```

------------------------------------------------------------------------

# Docker Image

Bake into image:

-   Python
-   uv
-   Project source
-   Python dependencies
-   FFmpeg
-   Git
-   ImageMagick (if required)
-   Required system libraries
-   CLI entrypoint
-   Runtime tools

Do NOT bake:

-   WhisperX models
-   Silero models
-   HuggingFace cache
-   Torch cache
-   Fonts that can be downloaded
-   Temporary cache
-   Workspace
-   Logs

Reason:

Keep image size reasonable.

Allow model upgrades independently.

------------------------------------------------------------------------

# Docker Volumes

Persist

``` text
workspace/
cache/
models/
logs/
```

Container rebuilds must never lose downloaded models.

------------------------------------------------------------------------

# Bootstrap Engine

Implement a dedicated bootstrap engine.

Responsibilities

## Workspace

Automatically create

workspace/

cache/

models/

logs/

debug/

music/

assets/

temp/

if missing.

------------------------------------------------------------------------

## Configuration

Validate

.env

Settings

Provider configuration

Model configuration

Workspace paths

Never silently change behavior.

If migration is needed:

perform migration.

------------------------------------------------------------------------

## Provider Validation

Verify every configured provider.

Examples

Gemini

Anthropic

Tavily

Groq

HuggingFace

Kokoro

WhisperX

Future providers

Validate

-   API key
-   connectivity
-   configured model
-   permissions

Produce diagnostics.

------------------------------------------------------------------------

## Model Bootstrap

Automatically download missing models.

Examples

WhisperX

Silero VAD

Future local models

Downloads should occur only once.

Reuse cached models.

Never redownload unnecessarily.

------------------------------------------------------------------------

## Dependency Validation

Verify

Python

FFmpeg

Git

ImageMagick

Torch

CUDA

GPU

Fonts

System libraries

ONNX Runtime

Report clear remediation if something is missing.

------------------------------------------------------------------------

# Self Healing

Implement automatic repair.

Examples

Missing directory

Missing model

Missing cache

Broken permissions

Corrupted cache

Missing font

Missing executable

Attempt repair automatically where safe.

------------------------------------------------------------------------

# CLI Commands

Create production CLI commands.

ytfactory setup

Complete bootstrap.

ytfactory doctor

Environment diagnostics.

ytfactory validate

Validate project.

ytfactory repair

Repair common issues.

ytfactory clean

Remove generated artifacts only.

ytfactory reset

Reset workspace while preserving configuration.

ytfactory update

Upgrade dependencies and migrate configuration.

------------------------------------------------------------------------

# Environment Report

Generate

environment-report.json

Include

OS

Python

Git

FFmpeg

Torch

CUDA

GPU

Installed providers

Enabled providers

Installed models

Workspace status

Configuration status

Dependency versions

Validation results

------------------------------------------------------------------------

# First Run Experience

Expected workflow

docker compose up

↓

Bootstrap starts

↓

Create directories

↓

Download WhisperX

↓

Download Silero

↓

Verify providers

↓

Prepare fonts

↓

Warm Torch cache

↓

Generate report

↓

Ready

------------------------------------------------------------------------

# Subsequent Runs

Expected

docker compose up

↓

Reuse cache

↓

Reuse models

↓

Reuse workspace

↓

Ready in seconds

------------------------------------------------------------------------

# Incremental Behaviour

Changing code:

Rebuild image.

Changing settings:

No image rebuild.

Changing models:

Download only changed models.

Changing providers:

Revalidate provider only.

------------------------------------------------------------------------

# Docker Profiles

Support

CPU

GPU

GPU profile should enable NVIDIA runtime automatically.

CPU should remain default.

------------------------------------------------------------------------

# Documentation

Rewrite installation guide.

Fresh machine should require only:

git clone

cp .env.example .env

docker compose up

ytfactory setup

ytfactory doctor

ytfactory build

Document every command.

------------------------------------------------------------------------

# Testing

Add tests for

Bootstrap

Workspace creation

Model download

Provider validation

Repair

Docker startup

CLI commands

Configuration migration

Run

Ruff

MyPy

Full pytest suite

------------------------------------------------------------------------

# Deliverables

-   Dockerfile
-   docker-compose.yml
-   Bootstrap Engine
-   Provider Validator
-   Model Bootstrap
-   Workspace Bootstrap
-   Self Healing Engine
-   Installation scripts
-   Production CLI
-   Documentation
-   Tests

------------------------------------------------------------------------

# Final Report

Provide

Implementation summary

Files modified

Files added

Docker architecture

Bootstrap flow

Configuration changes

Validation results

Remaining manual requirements

------------------------------------------------------------------------

# Success Criteria

A completely new machine should require only:

1.  Install Docker.
2.  Clone repository.
3.  Add API keys.
4.  Run Docker Compose.
5.  Run `ytfactory setup`.
6.  Build a video.

The resulting output must be identical to the current development
environment.

No hidden setup.

No manual debugging.

No environment-specific fixes.

The system should feel like a professional production application.
