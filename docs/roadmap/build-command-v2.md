# Build Command v2 Roadmap

## Goal

Simplify the entire YouTube Factory workflow into a **single command** while still allowing advanced users to execute individual pipeline stages.

The build command should intelligently determine what work needs to be performed based on the inputs and existing project artifacts.

---

# Objectives

- Single command to generate an entire video.
- Support both AI-generated scripts and user-provided scripts.
- Automatically create projects.
- Resume incomplete builds.
- Skip completed stages.
- Keep individual commands available for debugging.

---

# Workflow 1 — AI Generated Script

User provides only a topic.

```bash
uv run ytfactory build \
    --project history-of-shivaji \
    --title "History of Shivaji Maharaj"
```

Pipeline:

```
Create Project
      │
      ▼
Research
      │
      ▼
Generate Script (Gemini)
      │
      ▼
Scene Planning
      │
      ▼
Image Generation
      │
      ▼
Voice Generation
      │
      ▼
Caption Generation
      │
      ▼
Video Rendering
      │
      ▼
Publish Folder
```

No manual intervention required.

---

# Workflow 2 — Existing Script

User already has a script.

```bash
uv run ytfactory build \
    --project history-of-shivaji \
    --title "History of Shivaji Maharaj" \
    --script samples/scripts/history-of-shivaji.txt
```

Pipeline:

```
Create Project
      │
      ▼
Import Script
      │
      ▼
Scene Planning
      │
      ▼
Image Generation
      │
      ▼
Voice Generation
      │
      ▼
Caption Generation
      │
      ▼
Video Rendering
```

Research is skipped automatically.

---

# Intelligent Build

The build command should inspect the workspace before executing each stage.

Example:

```
Project exists?
    Yes
        ↓
Research exists?
    Yes
        ↓
Script exists?
    Yes
        ↓
Scenes exist?
    Yes
        ↓
Images exist?
    No
        ↓
Generate Images
        ↓
Generate Voice
        ↓
Generate Captions
        ↓
Render Video
```

Already completed stages should never be regenerated unless explicitly requested.

---

# Resume Support

The following should work:

```bash
uv run ytfactory build \
    --project history-of-shivaji
```

If the previous build stopped during image generation, the pipeline should continue from that point.

---

# Optional Flags

## Force rebuild

```bash
--force
```

Rebuild everything.

---

## Start from a stage

```bash
--from images
```

Example:

```
Images
↓

Voice

↓

Captions

↓

Video
```

---

## Stop after a stage

```bash
--to scenes
```

Example:

```
Create

↓

Research

↓

Script

↓

Scenes
```

---

## Skip a stage

```bash
--skip captions
```

Useful during development.

---

# Future Build Examples

## Generate everything

```bash
uv run ytfactory build \
    --project my-video \
    --title "My Video"
```

---

## Use existing script

```bash
uv run ytfactory build \
    --project my-video \
    --title "My Video" \
    --script script.txt
```

---

## Resume build

```bash
uv run ytfactory build \
    --project my-video
```

---

## Force rebuild

```bash
uv run ytfactory build \
    --project my-video \
    --force
```

---

## Build only until scenes

```bash
uv run ytfactory build \
    --project my-video \
    --to scenes
```

---

## Build from images onward

```bash
uv run ytfactory build \
    --project my-video \
    --from images
```

---

# Internal Responsibilities

The Build Pipeline becomes an orchestrator.

```
BuildPipeline

├── CreateProjectPipeline
├── ResearchPipeline
├── ScriptPipeline
├── ImportScriptPipeline
├── ScenePipeline
├── ImagePipeline
├── VoicePipeline
├── CaptionPipeline
├── VideoPipeline
└── PublishPipeline
```

Each pipeline remains independently executable.

---

# Benefits

- One command for the entire workflow.
- Supports AI-generated scripts and existing scripts.
- Automatically resumes interrupted builds.
- Faster development through stage skipping.
- Better user experience.
- Cleaner CLI.
- Production-ready orchestration.

---

# Estimated Effort

| Feature | Estimated Effort |
|----------|-----------------:|
| `--script` support | 1–2 hours |
| AI Script Writer | 3–5 hours |
| Intelligent resume | 4–8 hours |
| Build orchestration improvements | 1 day |
| Total (Build v2) | ~1–2 days |

---

# Proposed Release

**Version:** v2.0.0

Major Features:

- Single-command build
- AI Script Writer
- Existing script support
- Intelligent resume
- Stage skipping
- Force rebuild
- Build from specific stage
- Production-ready orchestration