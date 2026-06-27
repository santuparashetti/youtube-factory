# YouTube Factory Engineering Handbook

# Chapter 1 — Foundation

Version: 0.1.0

---

# Overview

## Project Name

**YouTube Factory**

## Repository

```
youtube-factory
```

## Python Package

```
ytfactory
```

## Goal

YouTube Factory is an open-source AI pipeline that converts a topic into a complete YouTube-ready package.

Long-term pipeline:

```
Topic
    ↓
Research
    ↓
Script
    ↓
Scene Planning
    ↓
Image Generation
    ↓
Narration
    ↓
Subtitles
    ↓
Video Composition
    ↓
Thumbnail
    ↓
SEO Package
    ↓
YouTube Ready
```

The system should support multiple AI providers (Gemini, OpenAI, Kimi, Ollama, etc.) through a provider abstraction.

---

# Sprint 1 Objective

Sprint 1 focuses only on building a solid foundation.

Deliverables:

* GitHub repository
* SSH authentication
* Python project
* uv package management
* Hatchling build system
* CLI using Typer
* Rich console output
* Workspace management
* Project creation command

No AI features are implemented in Sprint 1.

---

# System Requirements

Recommended:

* Ubuntu 22.04+
* Python 3.10+
* Git
* VS Code
* FFmpeg
* uv

---

# Installing Prerequisites

## Git

Verify:

```bash
git --version
```

Install if required:

```bash
sudo apt update
sudo apt install git
```

---

## Python

Verify:

```bash
python3 --version
```

Recommended:

```
Python 3.11+
```

(Current project built using Python 3.10.)

---

## Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the terminal.

Verify:

```bash
uv --version
```

---

## Install FFmpeg

```bash
sudo apt install ffmpeg
```

Verify:

```bash
ffmpeg -version
```

---

## Install VS Code

Verify:

```bash
code --version
```

---

# GitHub SSH Configuration

Example SSH configuration:

```
Host github-office
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519

Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
```

Verify:

```bash
ssh -T git@github-personal
```

Expected:

```
Hi <username>!
You've successfully authenticated...
```

---

# Repository Setup

Create a repository named:

```
youtube-factory
```

Clone:

```bash
git clone git@github-personal:<username>/youtube-factory.git

cd youtube-factory
```

---

# Initialize Project

Initialize using uv:

```bash
uv init --package .
```

---

# Runtime Dependencies

```bash
uv add typer rich loguru pydantic pydantic-settings pyyaml python-slugify
```

---

# Development Dependencies

```bash
uv add --dev pytest ruff mypy pre-commit hatchling
```

---

# Project Structure

Create folders:

```bash
mkdir -p \
src/ytfactory/{agents,cache,cli,config,jobs,models,prompts,providers,services,storage,utils,workflow} \
workspace/jobs \
assets \
docs
```

Create package markers:

```bash
find src -type d -exec touch {}/__init__.py \;
```

---

# Build System

Initially the project used **uv_build**, but it expected the Python package name to match the project name (`youtube_factory`), which conflicted with our desired package name (`ytfactory`).

We migrated to **Hatchling**.

`pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ytfactory"]
```

This resolved package discovery issues.

---

# Package Naming

Repository:

```
youtube-factory
```

Python package:

```
ytfactory
```

CLI:

```
ytfactory
```

---

# CLI Entry Point

Create:

```
src/ytfactory/__main__.py
```

```python
from ytfactory.cli.main import app

if __name__ == "__main__":
    app()
```

Development entry point:

```bash
uv run python -m ytfactory
```

---

# Sprint 1 Commands

Doctor:

```bash
uv run python -m ytfactory doctor
```

Version:

```bash
uv run python -m ytfactory version
```

Create project:

```bash
uv run python -m ytfactory create "History of Shivaji"
```

---

# Workspace Structure

Creating a project produces:

```
workspace/
└── jobs/
    └── history-of-shivaji/
        ├── assets/
        ├── audio/
        ├── cache/
        ├── images/
        ├── logs/
        ├── output/
        └── project.json
```

Each project has its own isolated workspace.

No global output directories are used.

---

# Git Ignore

Generated runtime artifacts must not be committed.

Recommended:

```
workspace/jobs/

!workspace/.gitkeep

.venv/

__pycache__/

.pytest_cache/

.mypy_cache/

.ruff_cache/

dist/

build/

*.egg-info/

.env
```

---

# Verification Checklist

Package import:

```bash
uv run python -c "import ytfactory; print(ytfactory.__file__)"
```

Doctor:

```bash
uv run python -m ytfactory doctor
```

Build:

```bash
uv build
```

Dependencies:

```bash
uv tree
```

---

# Sprint 1 Acceptance Criteria

* GitHub repository created
* SSH authentication working
* Project builds successfully
* Python package imports successfully
* CLI works
* `doctor` command works
* `version` command works
* `create` command works
* Workspace created successfully
* Runtime artifacts ignored by Git

---

# Lessons Learned

1. `uv_build` inferred the package name from the project name and expected `src/youtube_factory`, which conflicted with the chosen package name `ytfactory`.
2. Switching to Hatchling allowed explicit configuration of the package path.
3. During development, `uv run python -m ytfactory ...` is a reliable entry point.
4. Runtime-generated data belongs under `workspace/jobs/` and should be excluded from version control.

---

# Git Workflow

Daily workflow:

```bash
git add .
git commit -m "feat(...): description"
git push origin main
```

Use semantic version tags (for example `v0.1.0`) for releases rather than tagging every sprint.

---

# Sprint 2 Handoff

Sprint 2 begins with the first AI-powered feature.

Target command:

```bash
uv run python -m ytfactory research "History of Shivaji"
```

Expected output:

```
workspace/jobs/history-of-shivaji/
├── project.json
├── research.md
├── sources.json
└── logs/
```

The implementation should:

1. Load the project.
2. Invoke an LLM provider through an abstraction layer.
3. Generate structured research.
4. Save `research.md`.
5. Save `sources.json`.
6. Update `project.json`.
7. Display progress in the terminal.

Packaging and project foundation are considered complete unless a bug requires revisiting them.
