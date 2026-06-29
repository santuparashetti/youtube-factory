# YouTube Factory - Project Context
Version: v0.5.2
Last Updated: 2026-06-29

---

# Overview

YouTube Factory is a modular, provider-agnostic pipeline for generating YouTube videos using AI.

The long-term goal is to automate the complete workflow:

Research
→ Script
→ Scene Planning
→ Image Generation
→ Audio Generation
→ Subtitle Generation
→ Video Rendering
→ Publishing

The project follows clean architecture principles with provider abstraction, domain models, repositories, and independent feature pipelines.

---

# Current Version

Current Release:

v0.5.2

Git Status:

- main clean
- feature/image-generation merged
- all changes pushed
- Ruff passing
- MyPy passing

Git History

v0.3.0
Import Script Pipeline

v0.4.0
Scene Planner

v0.5.0
Image Architecture

v0.5.1
Cleanup

v0.5.2
Merged Image Generation into main

---

# Technology Stack

Language

Python 3.10

Package Manager

uv

CLI

Typer

Validation

Pydantic v2

Configuration

pydantic-settings

LLM

Google Gemini SDK

Research

Tavily

Image Generation

Google Gemini Image Models

Quality

ruff
mypy

---

# Current Folder Structure

src/ytfactory/

config/

domain/

providers/
    llm/
    image/
    search/
    tts/

research/
import_script/
scenes/
images/

voice/
captions/
video/
build/

storage/

shared/

workflow/

---

# Architecture Principles

The project follows these rules.

## 1. Provider Pattern

Every external service lives inside providers/.

Example:

providers/
    llm/
    image/
    search/
    tts/

No feature module should directly depend on an SDK.

Only providers communicate with external APIs.

---

## 2. Domain Layer

Shared business models belong inside domain/.

Examples

ImageRequest

ImageResponse

Scene

Script

Video

Audio

Project

The domain layer must never depend on providers.

---

## 3. Feature Pipelines

Every feature follows:

feature/

cli.py

models.py

pipeline.py

repository.py

Optional

prompts/

planner/

artifacts.py

---

## 4. Repository Pattern

Feature repositories own feature persistence.

Eventually:

research/repository.py

images/repository.py

audio/repository.py

video/repository.py

storage/ should eventually only contain generic filesystem implementations.

---

## 5. CLI

Every pipeline is exposed via Typer.

Current commands

doctor

create

research

import-script

plan-scenes

generate-images

---

# Provider Architecture

LLM

Gemini

Search

Tavily

Image

Gemini Image Provider

TTS

Planned

Kokoro

---

# Configuration

Settings lives in

src/ytfactory/config/settings.py

Current providers

LLM_PROVIDER=gemini

SEARCH_PROVIDER=tavily

IMAGE_PROVIDER=gemini_image

Current models

GEMINI_TEXT_MODEL=gemini-2.5-flash

GEMINI_IMAGE_MODEL=gemini-3.1-flash-image

---

# Image Generation

Status

Architecture Complete

Pipeline

CLI

Repository

Provider abstraction

Domain models

Factory

Implemented

Actual generation depends on Gemini image quota.

No ComfyUI.

No Automatic1111.

No OpenAI Images.

Project intentionally uses cloud provider abstraction.

---

# Quality

Current status

ruff

PASS

mypy

PASS

No TODO

No FIXME

No unused imports

Git clean

---

# Completed Milestones

Sprint 1

Foundation

DONE

Sprint 2

Research

DONE

Sprint 3

Import Script

DONE

Sprint 4

Scene Planner

DONE

Sprint 5

Image Architecture

DONE

---

# Remaining Roadmap

Sprint 6

Audio Generation

Provider

Kokoro

Sprint 7

Subtitle Generation

SRT

VTT

Sprint 8

Video Rendering

FFmpeg

Transitions

Zoom

Pan

Sprint 9

Publishing

YouTube Upload

Metadata

Thumbnail

Sprint 10

Web UI

Sprint 11

Automation

Sprint 12

Agent Orchestration

---

# Coding Standards

Always

Run

uv run ruff check .

uv run mypy src

before every commit.

Every sprint ends with

Git commit

Git tag

Git push

No failing Ruff.

No failing MyPy.

---

# Important Decisions

No OpenAI.

No ComfyUI.

No Automatic1111.

Gemini for LLM.

Gemini for Images.

Tavily for Search.

Kokoro planned for Audio.

Provider abstraction everywhere.

No SDK calls outside providers.

Domain models are shared.

Pipelines own orchestration.

Repositories own persistence.

---

# Future Improvements

Dependency Injection Container

Application Container

Filesystem abstraction

S3 support

GCS support

Parallel execution

Multi-provider support

Caching

Retry policies

Telemetry

Observability

---

# Current Project Health

Architecture

10/10

Git

10/10

Code Quality

10/10

Provider Pattern

10/10

Scalability

10/10

Overall

9.8/10

---

# Instructions for Future ChatGPT Sessions

Treat this repository as the source of truth.

Always preserve the existing architecture.

Never bypass providers.

Never bypass repositories.

Always produce complete file contents instead of snippets.

Always provide full file paths.

Always ensure Ruff and MyPy pass.

Prefer architectural consistency over shortcuts.

Build feature by feature.

Each sprint should end with

working CLI

passing Ruff

passing MyPy

Git commit

Git tag

Git push

Continue from the latest completed sprint without redesigning existing architecture unless explicitly requested.
