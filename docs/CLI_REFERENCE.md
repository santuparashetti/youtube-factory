# ytfactory CLI Reference

Complete reference for all `ytfactory` commands and options.

---

## Quick Decision Guide

| Situation | Command |
|---|---|
| Full video from scratch | `ytfactory run "Topic" --auto` |
| Pre-written script | `ytfactory run "Topic" --script path.md --auto` |
| Manual stage-by-stage control | `create` → `import-script` → `plan-scenes` → `generate-images` → … |
| Resume a failed run | `ytfactory run "Topic" --project PROJECT_ID --auto` |
| Re-run only changed stages | `ytfactory build PROJECT_ID --resume` |
| Replace one image and rebuild downstream | drop file → `ytfactory build PROJECT_ID --resume` |
| Force-regenerate specific stages | `ytfactory build PROJECT_ID --force-images` |
| Force-regenerate one scene | `ytfactory build PROJECT_ID --force-scene 8` |
| Review scene states | `ytfactory scene list PROJECT_ID` |
| Approve / reject / lock a scene | `ytfactory scene approve/reject/lock PROJECT_ID SCENE` |
| Write scene-review.md | `ytfactory scene review PROJECT_ID` |
| Check API keys and dependencies | `ytfactory doctor` |

---

## `ytfactory run` — Full Agentic Pipeline

The recommended command. Runs the complete pipeline end-to-end:

```
Research → Script → Scenes → Images + Voice (parallel) → Video → final.mp4
```

When `--script` is provided, research and script-writer stages are skipped:

```
Script Enhancer → Scenes → Images + Voice (parallel) → Video → final.mp4
```

When `--resume` is provided with `--project`, only changed/forced stages re-run (incremental mode).

```bash
ytfactory run TOPIC [OPTIONS]
```

### Arguments

| Argument | Required | Description |
|---|---|---|
| `TOPIC` | yes | Video topic or title (used as project name and LLM context) |

### Core Options

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--script` | `-s` | path | — | Path to a pre-written script file (`.md` or `.txt`). Skips research and script-writer; goes straight to the script enhancer. |
| `--style` | | text | — | Visual and narrative style. Values: `spiritual` \| `documentary` \| `educational` \| `history` |
| `--target-minutes` | `-t` | int | `7` | Target narration duration in minutes (range: 5–10). |
| `--language` | `-l` | text | `en` | BCP-47 language code for TTS voice selection. Examples: `en`, `hi`, `mr`, `es`, `fr` |
| `--auto` | | flag | off | Skip all human-review gates. Fully autonomous. |
| `--no-images` | | flag | off | Skip image generation. Saves `IMAGE_PROMPTS.md` — place images manually and re-run. |
| `--project` | `-p` | text | — | Resume an existing project by ID. Required for all incremental flags. |

### Incremental / Resume Options

These flags are only meaningful when `--project` is also provided (existing project).

| Option | Description |
|---|---|
| `--resume` | Skip stages whose outputs are unchanged. Detects changed files via SHA-256 checksums. |
| `--reuse-assets` | Alias for `--resume`. |
| `--force-images` | Force image regeneration (and all downstream: video → review → publish). |
| `--force-narration` | Force voice/TTS regeneration (and downstream: captions → video → review → publish). |
| `--force-subtitles` | Force caption regeneration (and downstream: video → review → publish). |
| `--force-motion` | Force motion re-planning and video render. |
| `--force-video` | Force full video re-render (and downstream: review → publish). |
| `--force-bgm` | Force BGM re-mix (implies `--force-video`). |
| `--force-publish` | Force publish package regeneration only. |
| `--scene N` | Scope change detection to scene N only. Combine with `--force-*` to target one scene. |
| `--force-scene N` | Force-regenerate scene N entirely (image + voice + captions + video). Overrides locked state. |

### Examples

```bash
# Full pipeline from scratch
ytfactory run "History of Shivaji" --auto

# Pre-written spiritual script, 8-minute target
ytfactory run "The Silent Force Controlling Your Life" \
  --script /tmp/script.md --style spiritual --target-minutes 8 --auto

# Skip images — review IMAGE_PROMPTS.md, place manually, then re-run
ytfactory run "Topic" --script /tmp/script.md --no-images --auto

# Resume a run that failed mid-way (same project, re-runs from where it stopped)
ytfactory run "Topic" --project the-silent-force-abc123 --auto

# Incremental: re-run only changed stages (detect via checksums)
ytfactory run "Topic" --project abc123 --resume

# Force images only (downstream stages auto-follow)
ytfactory run "Topic" --project abc123 --force-images

# Force narration + captions (e.g. after editing a script)
ytfactory run "Topic" --project abc123 --force-narration

# Replace image for scene 8 manually, then rebuild only that scene
cp my-new-image.png workspace/jobs/abc123/images/scene-008.png
ytfactory run "Topic" --project abc123 --resume

# Force-regenerate scene 8 entirely
ytfactory run "Topic" --project abc123 --force-scene 8

# Regenerate only the video for scene 3
ytfactory run "Topic" --project abc123 --scene 3 --force-video

# Hindi narration
ytfactory run "Shivaji Maharaj ka Itihas" --language hi --auto
```

---

## `ytfactory build` — Sequential Pipeline (with Incremental Support)

Runs the sequential pipeline without the agentic LangGraph layer. Requires a project ID from `ytfactory create`. Supports the same incremental flags as `ytfactory run`.

```bash
ytfactory build PROJECT_ID [OPTIONS]
```

### Core Options

| Option | Default | Description |
|---|---|---|
| `--skip-scenes` | off | Skip scene planning — use existing `scenes/scene-plan.json` |
| `--skip-images` | off | Skip image generation — use images already on disk |
| `--no-remediate` | off | Skip auto-remediation even if review fails |
| `--remediation-threshold` | `70.0` | Quality score threshold for auto-remediation (0–100) |
| `--remediation-retries` | `3` | Max auto-remediation retry cycles |

### Incremental / Resume Options

| Option | Description |
|---|---|
| `--resume` | Skip stages whose outputs are unchanged (SHA-256 checksum detection). |
| `--reuse-assets` | Alias for `--resume`. |
| `--force-images` | Force image regeneration. |
| `--force-narration` | Force voice/TTS regeneration. |
| `--force-subtitles` | Force caption regeneration. |
| `--force-video` | Force video re-render. |
| `--force-bgm` | Force BGM re-mix (implies `--force-video`). |
| `--force-publish` | Force publish package regeneration only. |
| `--scene N` | Scope change detection to scene N. |
| `--force-scene N` | Force-regenerate scene N entirely. |
| `--debug-incremental` | Print per-stage ✓ reused / ⚠ rebuilt table. |

### Examples

```bash
# Full build from scratch
ytfactory build abc123

# Incremental — only re-run what changed
ytfactory build abc123 --resume

# Force images then let downstream follow
ytfactory build abc123 --force-images

# Force scene 5 entirely
ytfactory build abc123 --force-scene 5

# Debug: see exactly which stages ran
ytfactory build abc123 --resume --debug-incremental

# Re-render only (scenes + images already exist)
ytfactory build abc123 --skip-scenes --skip-images
```

---

## `ytfactory scene` — Scene Approval Workflow

Manage per-scene states for the creator review process. States: Draft → Needs Review → Approved → Locked.

```bash
ytfactory scene COMMAND PROJECT_ID [OPTIONS]
```

### Commands

#### `scene list` — Show all scene states

```bash
ytfactory scene list PROJECT_ID
```

Prints a table of all scenes with their current state and notes.

#### `scene approve` — Approve a scene

```bash
ytfactory scene approve PROJECT_ID SCENE_INDEX
```

Marks the scene as Approved. Approved scenes are safe to include in the final video.

```bash
ytfactory scene approve abc123 3
```

#### `scene reject` — Mark Needs Revision

```bash
ytfactory scene reject PROJECT_ID SCENE_INDEX [--notes "reason"]
```

Marks the scene as Needs Revision. Optionally attach a reason.

```bash
ytfactory scene reject abc123 3 --notes "background looks wrong"
ytfactory scene reject abc123 8 --notes "narration too fast"
```

#### `scene lock` — Lock a scene

```bash
ytfactory scene lock PROJECT_ID SCENE_INDEX
```

Locks the scene. A locked scene is **never auto-regenerated** by any `--resume` or `--force-*` run. Only `scene unlock` or explicit `--force-scene N` overrides it.

```bash
ytfactory scene lock abc123 3
```

#### `scene unlock` — Unlock a scene

```bash
ytfactory scene unlock PROJECT_ID SCENE_INDEX
```

Returns a locked scene to Approved state.

```bash
ytfactory scene unlock abc123 3
```

#### `scene review` — Write scene-review.md

```bash
ytfactory scene review PROJECT_ID
```

Generates `workspace/jobs/PROJECT_ID/review/scene-review.md` — a full per-scene report with state, assets present/missing, narration, and motion type. Also prints a state summary to the console.

### State Lifecycle

```
Draft ──────────────────────────────→ Needs Review → Approved → Locked
  ↑                                         ↓             ↓
  └──────── Needs Revision ←────────────────┘             │
              (quality fail or scene reject)               │
                                                      scene unlock
```

| State | Meaning | Auto-regenerated? |
|---|---|---|
| Draft | Initial state after generation | Yes |
| Needs Review | Ready for creator inspection | Yes |
| Needs Revision | Failed quality review or rejected | Yes |
| Approved | Creator-approved | Yes |
| Locked | Manually locked by creator | **Never** |

### Manual Image Replacement Workflow

```bash
# 1. Drop your replacement image in place (same filename)
cp /path/to/better-image.png workspace/jobs/abc123/images/scene-008.png

# 2. Resume — auto-detects the changed file via SHA-256
ytfactory build abc123 --resume
# → scene-008 image: reused (your file)
# → motion: regenerated
# → scene-008 video: regenerated
# → final.mp4: rebuilt
# → review: rerun
# → publish: rerun

# 3. Lock the scene so future runs never touch it
ytfactory scene lock abc123 8
```

### Scene Examples — All Combinations

```bash
# List all scenes and their states
ytfactory scene list abc123

# Approve scene 3
ytfactory scene approve abc123 3

# Reject scene 8 with a note
ytfactory scene reject abc123 8 --notes "narrator too fast"

# Lock scene 5 (won't regenerate ever)
ytfactory scene lock abc123 5

# Unlock scene 5
ytfactory scene unlock abc123 5

# Write scene-review.md
ytfactory scene review abc123

# Force-regenerate only scene 8 (image + voice + captions + video)
ytfactory build abc123 --force-scene 8

# Force just the video for scene 3
ytfactory build abc123 --scene 3 --force-video

# Force just the image for scene 3
ytfactory build abc123 --scene 3 --force-images

# Force narration for scene 6
ytfactory build abc123 --scene 6 --force-narration
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

### `ytfactory setup`

First-run bootstrap: creates workspace, validates config and providers, provisions required models. Idempotent — safe to run multiple times.

```bash
ytfactory setup [--force]
```

| Flag | Description |
|---|---|
| `--force` | Re-run all checks even if already bootstrapped |

Expected output: `✓ Setup complete — environment ready`

### `ytfactory doctor`

Full health check without mutations. Checks environment, config, providers, and model states.

```bash
ytfactory doctor
```

### `ytfactory validate`

Lightweight config and provider check only (no workspace mutation, no model checks).

```bash
ytfactory validate
```

### `ytfactory repair`

Self-healing: recreates missing directories, fixes permissions, repairs broken symlinks.

```bash
ytfactory repair
```

### `ytfactory clean`

Deletes temporary files. Never touches `workspace/jobs/` or `models/`.

```bash
ytfactory clean [--logs] [--cache]
```

| Flag | Description |
|---|---|
| `--logs` | Also clean `logs/` directory |
| `--cache` | Also clean `cache/` directory |

### `ytfactory reset`

Removes bootstrap manifest and environment report. Re-run `ytfactory setup` after this.

```bash
ytfactory reset [--yes] [--workspace]
```

| Flag | Description |
|---|---|
| `--yes`, `-y` | Skip confirmation prompt |
| `--workspace` | **DESTRUCTIVE** — also deletes `workspace/jobs/` |

### `ytfactory update`

Re-validates environment after code or dependency updates. Force re-runs full setup.

```bash
ytfactory update
```

### `ytfactory version`

Prints version info and bootstrap manifest state.

```bash
ytfactory version
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

### Image Review (Vision Quality Gate)

| Key | Default | Description |
|---|---|---|
| `IMAGE_REVIEW_ENABLED` | `false` | Enable per-scene AI vision quality review |
| `VISION_REVIEW_PROVIDER` | `local` | Vision provider: `local` or `mock` |
| `VISION_REVIEW_LOCAL_MODEL` | `minicpm_v2_6` | Registry key of the local vision model |
| `IMAGE_REVIEW_MIN_SCORE` | `90` | Minimum vision score to accept a scene (0–100) |
| `IMAGE_REVIEW_CONFIDENCE` | `80` | Minimum confidence to trust the score (0–100) |
| `IMAGE_REVIEW_MAX_ATTEMPTS` | `3` | Max generation + review cycles per scene |
| `IMAGE_REVIEW_AUTO_REMEDIATE` | `true` | Refine prompt and regenerate on FAIL |
| `IMAGE_REVIEW_DEBUG` | `false` | Write per-attempt prompt files to `images/` |

Enabling image review requires `torch`, `transformers`, `pillow` and ~10 GB disk for the MiniCPM-V 2.6 model. Run `ytfactory setup` after enabling — the Local AI Model Manager provisions the model automatically.

---

## Workspace Layout

All project files are written to `workspace/jobs/PROJECT_ID/`:

```
workspace/jobs/PROJECT_ID/
├── project.json              # Project metadata and stage statuses
├── .pipeline-manifest.json   # SHA-256 checksums for incremental builds
├── research/
│   └── research.md           # Web research summary
├── script/
│   ├── script.md             # Final script (used by scene planner)
│   └── script_original.md    # Your original script before enhancement
├── scenes/
│   ├── scene-plan.json       # Scene plan (narration, visual prompts, durations)
│   └── scene-status.json     # Per-scene approval states (Draft/Approved/Locked…)
├── images/
│   ├── scene-001.png              # Generated or manually placed images
│   ├── IMAGE_PROMPTS.md           # Visual prompts (--no-images mode)
│   ├── manifest.json
│   ├── image-quality-summary.json # Vision review summary (when IMAGE_REVIEW_ENABLED=true)
│   ├── image-review-NNN.json      # Per-scene vision review result
│   └── image-remediation-NNN.json # Per-scene remediation history
├── audio/
│   └── scene-001.mp3         # TTS narration audio
├── subtitles/
│   └── scene-001.srt         # Frame-accurate subtitles
├── video/
│   ├── scene-001.mp4         # Per-scene rendered clips
│   └── final.mp4             # Final concatenated video
└── review/
    ├── review-report.md      # Quality gate summary
    ├── scene-review.md       # Per-scene status report (ytfactory scene review)
    └── …                     # Validation, RCA, scoring, EFL reports
```
