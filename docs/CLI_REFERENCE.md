# ytfactory CLI Reference

Complete reference for all `ytfactory` commands and options.

---

## Quick Decision Guide

| Situation | Command |
|---|---|
| Full video from scratch (research + script + video) | `ytfactory run "Topic" --auto` |
| You have a pre-written script | `ytfactory run "Topic" --script path.md --auto` |
| You want to control each stage manually | `create` → `import-script` → `plan-scenes` → `generate-images` → ... |
| Resume a failed run | `ytfactory run "Topic" --project PROJECT_ID --auto` |
| Check API keys and dependencies | `ytfactory doctor` |

---

## `ytfactory run` — Full Agentic Pipeline

The recommended command. Runs the complete pipeline end-to-end:

```
Research → Script → Scenes → Images + Voice (parallel) → Video → final.mp4
```

When `--script` is provided, the research and script-writer stages are skipped:

```
Script Enhancer → Scenes → Images + Voice (parallel) → Video → final.mp4
```

```bash
ytfactory run TOPIC [OPTIONS]
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `TOPIC` | yes | Video topic or title (used as project name and LLM context) |

### Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--script` | `-s` | path | — | Path to a pre-written script file (`.md` or `.txt`). Skips research and script-writer; goes straight to the script enhancer. |
| `--style` | | text | — | Visual and narrative style applied by the script enhancer and image prompts. Values: `spiritual` \| `documentary` \| `educational` \| `history` |
| `--target-minutes` | `-t` | int | `7` | Target narration duration in minutes (range: 5–10). The script enhancer expands your raw script to approximately `target_minutes × 130` words. |
| `--language` | `-l` | text | `en` | BCP-47 language code for TTS voice selection. Examples: `en`, `hi`, `mr`, `es`, `fr` |
| `--auto` | | flag | off | Skip all human-review gates. Runs fully autonomously without pausing for approval. |
| `--no-images` | | flag | off | Skip image generation. Saves `workspace/jobs/PROJECT_ID/images/IMAGE_PROMPTS.md` — generate or place images manually, then re-run the same command (images already on disk are not regenerated). |
| `--project` | `-p` | text | — | Resume an existing project by its ID. Skips project creation. Useful for retrying failed runs or re-rendering with different settings. |

### Examples

```bash
# Full pipeline from scratch — research + write + produce
ytfactory run "History of Shivaji" --auto

# Pre-written spiritual script, 8-minute target
ytfactory run "The Silent Force Controlling Your Life" \
  --script /tmp/atma_theory_the_silent_force.md \
  --style spiritual \
  --target-minutes 8 \
  --auto

# Pre-written script — skip images, review prompts, place manually
ytfactory run "The Silent Force Controlling Your Life" \
  --script /tmp/script.md \
  --style spiritual \
  --no-images --auto

# Resume a run that failed mid-way
ytfactory run "The Silent Force Controlling Your Life" \
  --project the-silent-force-abc123 \
  --auto

# Hindi narration from research
ytfactory run "Shivaji Maharaj ka Itihas" --language hi --auto

# Full options combined
ytfactory run "The Ego and the Self" \
  --script /tmp/ego_script.md \
  --style spiritual \
  --target-minutes 8 \
  --language en \
  --auto
```

---

## `ytfactory build` — Legacy Sequential Pipeline

Runs the older sequential pipeline without agentic enhancement. Requires a project ID created by `ytfactory create`. Useful when you want direct control without the LangGraph agent layer.

```bash
ytfactory build PROJECT_ID [OPTIONS]
```

### Options

| Option | Default | Description |
|---|---|---|
| `--skip-scenes` | off | Skip scene planning — use the existing `scenes/scene-plan.json` |
| `--skip-images` | off | Skip image generation — use images already on disk |

### Example

```bash
ytfactory create "The Power of Silence"
# manually write workspace/jobs/PROJECT_ID/script/script.md
ytfactory build the-power-of-silence-abc123
ytfactory build the-power-of-silence-abc123 --skip-scenes --skip-images  # re-render only
```

---

## Manual Step-by-Step Commands

Use when you need to debug a specific stage, inspect intermediate outputs, or run stages selectively.

### `ytfactory create`

Creates a new project and prints the project ID.

```bash
ytfactory create "My Video Title"
# → created project: my-video-title-abc123
```

### `ytfactory research`

Runs web research on the topic and writes `research/research.md`.

```bash
ytfactory research PROJECT_ID
```

### `ytfactory import-script`

Imports a script file into the project workspace, writing it to `script/script.md`.

```bash
ytfactory import-script PROJECT_ID /path/to/script.md
```

### `ytfactory plan-scenes`

Parses the script and generates `scenes/scene-plan.json`. Each scene gets a narration excerpt, visual prompt, and duration estimate.

```bash
ytfactory plan-scenes PROJECT_ID
```

### `ytfactory generate-images`

Generates one image per scene using the configured image provider. Skips scenes that already have an image on disk.

```bash
ytfactory generate-images PROJECT_ID
```

### `ytfactory generate-voice`

Generates TTS audio for each scene's narration using the configured TTS provider. Produces per-scene `.mp3` files.

```bash
ytfactory generate-voice PROJECT_ID
```

### `ytfactory generate-captions`

Generates frame-accurate `.srt` subtitle files for each scene from the TTS word-boundary events.

```bash
ytfactory generate-captions PROJECT_ID
```

### `ytfactory render`

Renders all scene clips (image + audio + subtitles → `.mp4`) and concatenates them into `video/final.mp4`.

```bash
ytfactory render PROJECT_ID
```

### `ytfactory doctor`

Checks API keys, provider connectivity, FFmpeg availability, and workspace permissions.

```bash
ytfactory doctor
```

---

## Full Manual Workflow

```bash
# 1. Create project
ytfactory create "My Video Title"
# → note the PROJECT_ID printed

# 2a. Research (if writing script from scratch)
ytfactory research PROJECT_ID

# 2b. Import your own script (skips research)
ytfactory import-script PROJECT_ID /path/to/script.md

# 3. Plan scenes
ytfactory plan-scenes PROJECT_ID

# 4. Generate images
ytfactory generate-images PROJECT_ID

# 5. Generate voice
ytfactory generate-voice PROJECT_ID

# 6. Generate captions
ytfactory generate-captions PROJECT_ID

# 7. Render
ytfactory render PROJECT_ID

# Final video: workspace/jobs/PROJECT_ID/video/final.mp4
```

---

## `.env` Settings

These environment variables in `.env` apply globally to every run.

### API Keys

| Key | Description |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key |
| `TAVILY_API_KEY` | Tavily search API key (used by research stage) |
| `HF_TOKEN` | Hugging Face token (for FLUX image generation) |
| `GROQ_API_KEY` | Groq API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `ANTHROPIC_BASE_URL` | Anthropic base URL (override for proxies/LiteLLM) |

### Providers

| Key | Default | Options |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | `anthropic` \| `gemini` \| `groq` \| `ollama` |
| `IMAGE_PROVIDER` | `huggingface` | `huggingface` \| `gemini` \| `pollinations` |
| `TTS_PROVIDER` | `edge` | `edge` \| `elevenlabs` |
| `SEARCH_PROVIDER` | `tavily` | `tavily` |

### Models

| Key | Default | Description |
|---|---|---|
| `ANTHROPIC_MODEL` | `claude-haiku-4-5` | Anthropic model ID |
| `GEMINI_TEXT_MODEL` | `gemini-2.5-flash` | Gemini text model |
| `GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-lite-image` | Gemini image model |
| `HF_IMAGE_MODEL` | `black-forest-labs/FLUX.1-schnell` | Hugging Face image model |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | Groq model ID |

### Image & Video

| Key | Default | Description |
|---|---|---|
| `IMAGE_WIDTH` | `1280` | Image generation width (pixels) |
| `IMAGE_HEIGHT` | `720` | Image generation height (pixels) |
| `VIDEO_WIDTH` | `1920` | Output video width (pixels) |
| `VIDEO_HEIGHT` | `1080` | Output video height (pixels) |

### Rendering

| Key | Default | Description |
|---|---|---|
| `RENDER_PROFILE` | `balanced` | Cinematic quality profile applied to every render |

**Render profile options:**

| Profile | Motion | Transitions | Effects | Use When |
|---|---|---|---|---|
| `draft` | None (static) | Hard cuts | None | Fastest render, testing scene plan |
| `balanced` | Simple zoom/pan | Cross-dissolves | None | Default, clean output |
| `cinematic` | Full emotion-aware (8 types) | Emotion-pair transitions | Color grade + vignette | Production quality |
| `premium` | Full emotion-aware, wider range | Emotion-pair transitions + longer fades | Color grade + vignette + film grain | Maximum quality |

---

## Workspace Layout

All project files are written to `workspace/jobs/PROJECT_ID/`:

```
workspace/jobs/PROJECT_ID/
├── project.json            # Project metadata and stage statuses
├── research/
│   └── research.md         # Web research summary
├── script/
│   ├── script.md           # Final script (used by scene planner)
│   └── script_original.md  # Your original script before enhancement
├── scenes/
│   └── scene-plan.json     # Scene plan (narration, visual prompts, durations)
├── images/
│   ├── scene-001.png       # Generated or asset images
│   ├── IMAGE_PROMPTS.md    # Visual prompts (--no-images mode)
│   └── manifest.json
├── audio/
│   └── scene-001.mp3       # TTS narration audio
├── subtitles/
│   └── scene-001.srt       # Frame-accurate subtitles
└── video/
    ├── scene-001.mp4       # Per-scene rendered clips
    └── final.mp4           # Final concatenated video
```
