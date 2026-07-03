# 🎬 YouTube Factory

> An open-source AI-powered content production pipeline that transforms a topic into a complete YouTube-ready video.

---

## Vision

Creating high-quality YouTube videos typically involves multiple manual steps:

* Research
* Script writing
* Scene planning
* Image generation
* Voice-over
* Subtitles
* Video editing
* Thumbnail creation
* SEO optimization

**YouTube Factory** automates this entire workflow using AI while keeping the system modular, configurable, and provider-agnostic.

---

## Project Status

**Current Version**

```
Sprint 1 — Foundation ✅
```

Current capabilities:

* ✅ Project initialization
* ✅ CLI
* ✅ Workspace management
* ✅ Build system
* ✅ Development environment

AI features will be introduced beginning with Sprint 2.

---

# Long-Term Pipeline

```text
Topic
    │
    ▼
Research Agent
    │
    ▼
Script Writer
    │
    ▼
Scene Planner
    │
    ▼
Image Generator
    │
    ▼
Narration
    │
    ▼
Subtitles
    │
    ▼
Video Composer
    │
    ▼
Thumbnail Generator
    │
    ▼
SEO Package
    │
    ▼
YouTube Ready
```

---

# Goals

* Open Source
* Modular Architecture
* Multiple AI Providers
* Low Operating Cost
* Production Quality
* Resumeable Workflow
* Human Review Friendly

---

# Planned AI Providers

The architecture is designed so providers can be swapped without changing business logic.

Planned providers include:

* Gemini
* OpenAI
* Kimi
* Ollama
* Future Local Models

---

# Technology Stack

| Component        | Technology        |
| ---------------- | ----------------- |
| Language         | Python            |
| Package Manager  | uv                |
| CLI              | Typer             |
| Console          | Rich              |
| Configuration    | Pydantic Settings |
| Logging          | Loguru            |
| Build            | Hatchling         |
| Testing          | pytest            |
| Linting          | Ruff              |
| Type Checking    | MyPy              |
| Video Processing | FFmpeg            |

---

# Repository Structure

```text
youtube-factory/

assets/
docs/
workspace/

src/
└── ytfactory/

tests/

README.md
pyproject.toml
uv.lock
```

---

# Development

## Run Doctor

```bash
uv run python -m ytfactory doctor
```

---

## Show Version

```bash
uv run python -m ytfactory version
```

---

## Create Project

```bash
uv run python -m ytfactory create "History of Shivaji"
```

---

# Example Workspace

```text
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

Each project is isolated in its own workspace.

---

# Documentation

Project documentation lives inside the `docs/` directory.

Recommended reading order:

```text
docs/

manual/
    01-foundation.md

architecture/

decisions/

prompts/
```

---
# YouTube Factory

This README summarizes the current v1.0.0 pipeline.

## Workflows

### 1. AI Research Workflow

``` bash
ytfactory create <project> --title "Title"
ytfactory research <project>
# create script.md manually
ytfactory plan-scenes <project>
ytfactory generate-images <project>
ytfactory generate-voice <project>
ytfactory generate-captions <project>
ytfactory render <project>
```

Or:

``` bash
ytfactory build <project>
```

### 2. Existing Script Workflow

``` bash
ytfactory create <project> --title "Title"
ytfactory import-script <project> samples/scripts/script.txt
ytfactory plan-scenes <project>
ytfactory generate-images <project>
ytfactory generate-voice <project>
ytfactory generate-captions <project>
ytfactory render <project>
```

Or:

``` bash
ytfactory build <project>
```

## Notes

-   Images: 1920x1080 (16:9)
-   Video: 1920x1080
-   Edge TTS
-   Hugging Face FLUX
-   Gemini + Tavily


Target command:

```bash
uv run python -m ytfactory run "History of Shivaji"
```

---


# Contributing

Contributions are welcome.

Please read the documentation inside the `docs/` directory before submitting pull requests.

---

# License

MIT License

---

# Author

**Santosh Parashetti**

---

# Acknowledgements

This project is built using modern open-source tools including:

* Python
* uv
* Typer
* Rich
* Hatchling
* FFmpeg

Special thanks to the open-source community for making these technologies available.
