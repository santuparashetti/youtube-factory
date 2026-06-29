# 🎬 YouTube Factory

> AI-powered end-to-end YouTube video generation pipeline.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Status](https://img.shields.io/badge/status-v1.0.0-success)
![License](https://img.shields.io/badge/license-MIT-green)

------------------------------------------------------------------------

# Overview

YouTube Factory automates creation of YouTube videos from either:

1.  A topic (AI research workflow)
2.  An existing script

It generates:

-   Research
-   Script (manual today, AI planned)
-   Scene plan
-   AI images
-   AI narration
-   Subtitles
-   Final 1920×1080 video

------------------------------------------------------------------------

# Architecture

``` text
Topic
  │
  ▼
Research (Gemini + Tavily)
  │
  ▼
Script
  │
  ▼
Scene Planner
  │
  ▼
Image Generator (HF FLUX)
  │
  ▼
Voice (Edge TTS)
  │
  ▼
Captions
  │
  ▼
FFmpeg Renderer
  │
  ▼
YouTube-ready Video
```

------------------------------------------------------------------------

# Installation

``` bash
git clone <repo-url>
cd youtube-factory
uv sync
```

## Configure

Create `.env`

``` env
GEMINI_API_KEY=
TAVILY_API_KEY=
HF_TOKEN=

LLM_PROVIDER=gemini
SEARCH_PROVIDER=tavily
IMAGE_PROVIDER=huggingface
TTS_PROVIDER=edge

GEMINI_TEXT_MODEL=gemini-2.5-flash
HF_IMAGE_MODEL=black-forest-labs/FLUX.1-schnell

IMAGE_WIDTH=1920
IMAGE_HEIGHT=1080
```

Verify

``` bash
uv run ytfactory doctor
```

------------------------------------------------------------------------

# Project Layout

``` text
workspace/
└── jobs/
    └── <project>/
        ├── project.json
        ├── research/
        ├── script/
        ├── scenes/
        ├── images/
        ├── audio/
        ├── subtitles/
        ├── video/
        └── publish/
```

------------------------------------------------------------------------

# Workflow 1 -- AI Research

``` bash
uv run ytfactory create history-of-shivaji \
    --title "History of Shivaji Maharaj"

uv run ytfactory research history-of-shivaji
```

Create:

``` text
workspace/jobs/history-of-shivaji/script/script.md
```

Then

``` bash
uv run ytfactory plan-scenes history-of-shivaji
uv run ytfactory generate-images history-of-shivaji
uv run ytfactory generate-voice history-of-shivaji
uv run ytfactory generate-captions history-of-shivaji
uv run ytfactory render history-of-shivaji
```

------------------------------------------------------------------------

# Workflow 2 -- Existing Script

``` bash
uv run ytfactory create my-video \
    --title "My Video"

uv run ytfactory import-script \
    my-video \
    samples/scripts/my-video.txt

uv run ytfactory plan-scenes my-video
uv run ytfactory generate-images my-video
uv run ytfactory generate-voice my-video
uv run ytfactory generate-captions my-video
uv run ytfactory render my-video
```

------------------------------------------------------------------------

# Current Build Command

``` bash
uv run ytfactory build my-video
```

Current pipeline:

``` text
Scene Planning
      ↓
Image Generation
      ↓
Voice Generation
      ↓
Caption Generation
      ↓
Video Rendering
```

------------------------------------------------------------------------

# Planned Build v2

Single intelligent command:

``` bash
uv run ytfactory build \
    --project history-of-shivaji \
    --title "History of Shivaji Maharaj"
```

or

``` bash
uv run ytfactory build \
    --project history-of-shivaji \
    --title "History of Shivaji Maharaj" \
    --script samples/scripts/history-of-shivaji.txt
```

Features:

-   Automatic project creation
-   Existing script support
-   AI script generation
-   Resume failed builds
-   Skip completed stages
-   Force rebuild
-   Stage selection

------------------------------------------------------------------------

# Output

``` text
images/
audio/
subtitles/
video/
publish/
```

All outputs are native **1920×1080 (16:9)**.

------------------------------------------------------------------------

# Tech Stack

-   Python
-   UV
-   Gemini
-   Tavily
-   Hugging Face FLUX
-   Edge TTS
-   FFmpeg
-   Pydantic
-   Typer

------------------------------------------------------------------------

# Roadmap

-   AI Script Writer
-   Intelligent Build v2
-   Thumbnail Generator
-   Background Music
-   Scene Transitions
-   YouTube Upload
-   SEO Metadata
-   Multi-language
-   Batch Processing
-   Parallel Rendering

------------------------------------------------------------------------

# Version

**v1.0.0**
