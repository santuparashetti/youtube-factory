# YouTube Factory - Development Context

## Sprint 1 Completed

> This file contains the current project context so that development can continue in a new AI session without losing architectural decisions.

---

# Project

Name: YouTube Factory

Goal:

Build an open-source AI pipeline that converts a topic or script into a complete YouTube-ready video.

The pipeline will eventually perform:

Topic
→ Research
→ Script
→ Scene Planning
→ Image Generation
→ Narration
→ Subtitles
→ Video Composition
→ Thumbnail
→ SEO Package

The project should support multiple AI providers and minimize operating cost by using free or inexpensive models wherever possible.

---

# Development Philosophy

This is not a demo project.

The goal is to build a production-quality open-source framework.

Architecture is more important than writing large amounts of code quickly.

Every sprint must leave the repository in a runnable state.

---

# Repository

Repository Name

youtube-factory

Python Package

ytfactory

Development Entry Point

```bash
uv run python -m ytfactory
```

Repository is hosted on GitHub.

SSH authentication is configured.

Main branch is working.

Sprint tags have been removed.

---

# Environment

Operating System

Ubuntu 22.04

Python

3.10

Package Manager

uv

Build Backend

Hatchling

CLI

Typer

Console

Rich

Logging

Loguru

Configuration

Pydantic Settings

Build

uv build

works successfully.

---

# Repository Structure

```text
youtube-factory/

assets/

docs/

workspace/
    .gitkeep

src/
└── ytfactory/
    ├── __init__.py
    ├── __main__.py
    ├── cli/
    ├── agents/
    ├── cache/
    ├── config/
    ├── jobs/
    ├── models/
    ├── prompts/
    ├── providers/
    ├── services/
    ├── storage/
    ├── utils/
    └── workflow/

README.md

pyproject.toml

uv.lock
```

---

# Current Working Commands

Doctor

```bash
uv run python -m ytfactory doctor
```

Version

```bash
uv run python -m ytfactory version
```

Create Project

```bash
uv run python -m ytfactory create "History of Shivaji"
```

These commands are fully working.

---

# Workspace Structure

Creating a project generates:

```text
workspace/jobs/

history-of-shivaji/

project.json

assets/

audio/

cache/

images/

logs/

output/
```

Runtime data is ignored by Git.

workspace/jobs/

is listed in .gitignore.

workspace/.gitkeep

keeps the folder in Git.

---

# Sprint 1 Status

Completed

Implemented

✓ CLI

✓ Project Creation

✓ Package Build

✓ Workspace Generation

✓ Project Metadata

✓ GitHub Setup

✓ SSH Setup

✓ Build System

Not Yet Implemented

✗ Status Command

✗ Research

✗ Script

✗ Scene Planning

✗ Image Generation

✗ Voice

✗ Video

✗ Thumbnail

✗ SEO

---

# Important Architecture Decisions

Repository Name

youtube-factory

Python Package

ytfactory

Every YouTube video is represented as a Project.

Each Project owns an isolated workspace.

Future AI agents will only work inside the project workspace.

No global state.

No shared output folders.

Runtime artifacts are never committed to Git.

---

# Development Rules

Always use

```bash
uv run python -m ytfactory
```

during development.

Do not rely on globally installed commands.

Build must always succeed.

Every sprint should end with working commands.

No placeholder code.

Every class should be used immediately.

---

# AI Strategy

The system should support multiple providers.

The architecture must allow plugging in different LLMs without changing business logic.

Planned providers:

Gemini

OpenAI

Kimi

Ollama

Future local models

Business logic should never depend directly on a specific provider.

---

# Planned Architecture

Preferred direction:

Feature-first (vertical slice) architecture.

Future modules:

projects/

research/

script/

scene/

image/

voice/

video/

publish/

Each module should contain its own:

model

service

repository

commands

instead of separating everything into global models/services folders.

This migration has NOT been performed yet.

Current folder structure remains unchanged.

Future work may reorganize it carefully.

---

# Coding Standards

Use:

Typer

Rich

Pydantic

Loguru

Avoid global variables.

Use strong typing.

Business logic should not live inside CLI commands.

CLI should call services.

Services should call providers.

---

# Git Workflow

Current branch:

main

Normal workflow:

git add .

git commit -m "feat(...): ..."

git push origin main

Do not create sprint tags.

Reserve Git tags for releases only.

Examples:

v0.1.0

v0.2.0

v1.0.0

---

# Sprint 2 Goal

Implement the first AI feature.

Command:

```bash
uv run python -m ytfactory research "History of Shivaji"
```

Expected Output

```text
workspace/jobs/history-of-shivaji/

project.json

research.md

sources.json

logs/
```

The command should:

1. Read project.json.
2. Call an LLM provider.
3. Generate structured research.
4. Save research.md.
5. Save sources.json.
6. Update project.json.
7. Display progress in the terminal.

No image generation in Sprint 2.

Only research.

---

# Long-Term Roadmap

Sprint 1

Foundation ✅

Sprint 2

Research Agent

Sprint 3

Script Writer

Sprint 4

Scene Planner

Sprint 5

Image Prompt Generator

Sprint 6

Image Generation

Sprint 7

Narration + Subtitles

Sprint 8

Video Composer

Sprint 9

Thumbnail + SEO

Sprint 10

One-command YouTube Factory

Final command:

```bash
uv run python -m ytfactory run "History of Shivaji"
```

This command should execute the complete pipeline end-to-end.

---

# Instructions for the Next AI Session

Assume Sprint 1 is complete.

Do not revisit packaging, repository setup, or CLI foundation unless there is a bug.

Continue implementation from Sprint 2.

Prioritize clean architecture, modularity, and production-quality code.

Avoid unnecessary refactoring unless it provides a clear long-term benefit.

The next implementation target is the Research Agent and the provider abstraction needed to support multiple LLMs.
