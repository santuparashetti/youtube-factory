# YouTube Factory — Pipeline Architecture

> Last updated: 2026-07-04  
> Engine: LangGraph agentic pipeline (`ytfactory run`)

---

## Overview

YouTube Factory converts a topic or a hand-written script into a complete YouTube video through a series of AI-powered and Python stages. The pipeline is built on **LangGraph** (a directed graph of nodes with typed state), which enables conditional routing, parallel fan-out, idempotency, and human-in-the-loop review gates.

---

## Two Entry Modes

```
MODE A — Research path (no script)          MODE B — Script path (--script flag)
─────────────────────────────────           ─────────────────────────────────────
ytfactory run "Topic" --auto                ytfactory run "Topic" \
                                              --script my_script.md \
                                              --style spiritual \
                                              --no-images \
                                              --auto
```

The entry point is a **conditional edge** from `START` that checks whether `script_md` is present in the pipeline state:

- **`script_md` present** → `script_enhancer` → `scene_planner`
- **No script** → `research_agent` → `script_writer` → `human_review_script` → `scene_planner`

---

## Full Graph

```
START
  │
  ├─[has script?]─── YES ──► script_enhancer ──────────────────────────┐
  │                                                                     │
  └─── NO ──► research_agent ──► script_writer ──► human_review_script ┘
                                                                        │
                                                               scene_planner
                                                                        │
                                                          human_review_scenes
                                                                        │
                                              ┌─────────────────────────┤ (parallel Send fan-out)
                                              │                         │
                                   generate_scene_assets × N scenes
                                    (image + audio + subtitle per scene)
                                              │
                                              ├─[skip_images=True]──► END
                                              │
                                         video_renderer (per scene → .mp4)
                                              │
                                        video_concatenator (→ final.mp4)
                                              │
                                             END
```

---

## Stage-by-Stage Breakdown

### 1. `script_enhancer` _(Script path only)_

**File:** `src/ytfactory/agents/nodes/script_enhancer.py`  
**Prompt:** `src/ytfactory/agents/prompts/script_enhancer.py`

Takes the user's raw seed script and **expands + rewrites** it into a full cinematic narration:

- **Target:** ~780 words (6 min at 130 wpm baseline)
- **Expansion rules:** Every concept in the raw script gets elaborated with examples, metaphors, and transitions. Short seed scripts (400-600 words) are expanded to 700-900 words.
- **Style-aware voice guide:** Spiritual, documentary, history, educational — each has its own tone, rhythm, and language rules baked into the prompt.
- **TTS-safe output:** No markdown, no asterisks, no abbreviations. Numbers spelled out. Every word must be immediately pronounceable.
- **Saves:** `script_original.md` (input) + `script.md` (enhanced output) to workspace.

**Key design decision:** The enhancer uses `temperature=0.6` (higher creativity) since this is a creative writing task, not a structured data task.

---

### 2. `research_agent` _(Research path only)_

**File:** `src/ytfactory/agents/nodes/research.py`

- Multi-query web search via Tavily (3-5 diverse queries)
- Sources capped at 12, 1,200 chars each (prevents 95KB prompts that cause connection drops)
- LLM synthesises research into `research.md`

---

### 3. `script_writer` _(Research path only)_

**File:** `src/ytfactory/agents/nodes/script_writer.py`

- Converts `research.md` → `script.md`
- Targets 130 wpm pacing, checks hook quality and CTA presence

---

### 4. `scene_planner`

**File:** `src/ytfactory/agents/nodes/scene_planner.py`  
**Prompt:** `src/ytfactory/agents/prompts/scene_planner.py`

**Two-phase design** (evolved to avoid Groq output token truncation):

#### Phase 1 — Python script splitter (no LLM)

The LLM was reliably truncating large JSON outputs (28 scenes × full narrations + visual prompts = ~4,000 tokens). Replaced with deterministic Python splitting:

```
_split_script_to_scenes(script, target_words=28)
```

- Strips residual markdown from the enhanced script
- Splits each paragraph into individual sentences using regex on `.!?…` boundaries
- Groups sentences into ~28-word buckets (scene ≈ 12-15 seconds at -20% TTS rate)
- Flushes at paragraph breaks when the bucket is ≥60% full
- Produces 20-28 scenes from a 700-word script
- **Zero LLM calls, zero truncation risk, 100% verbatim narration**

#### Phase 2 — Visual prompts (LLM, batched by 7)

28 prompts in one LLM call → truncated after scene 1. Now batched:

```
for batch in chunks(scenes, size=7):
    llm.generate(build_visual_prompts_prompt(batch, style))
```

- Each call: 7 scenes × ~40 words = ~280 token output → never truncated
- Style guide injected (spiritual, documentary, etc.)
- Prompts specify: shot type, lighting, colour palette, no text/faces
- Falls back to title-based placeholder if a batch fails

#### Artifacts written

| File | Contents |
|---|---|
| `scenes/scene-plan.json` | Full scene plan (narrations + visual prompts + durations) |
| `scenes/scene-plan.md` | Human-readable summary |
| `images/IMAGE_PROMPTS.md` | Ready-to-use prompts for external image tools |

**Idempotency:** If `scene-plan.json` already exists, the node loads it from disk and skips all LLM calls.

---

### 5. `generate_scene_assets` _(Parallel fan-out)_

**File:** `src/ytfactory/agents/nodes/scene_assets.py`

LangGraph `Send` API dispatches one copy of this node per scene, all running in parallel. Each copy handles one scene independently.

#### 5a. Image generation (skippable)

- Skipped entirely when `skip_images=True` (`--no-images` flag)
- Skipped per-scene if `scene-NNN.png` already exists (idempotent)
- Staggered start: `time.sleep(index × 3)` to avoid API burst rate limits
- 5 retry attempts with exponential backoff (15s → 30s → 60s → 120s → 240s)
- Provider: **Pollinations.ai** (free, `flux-realism` model) — switched from Gemini which requires billing

**Manual image workflow:**
1. Run with `--no-images` → get `images/IMAGE_PROMPTS.md`
2. Generate images in Leonardo AI / Adobe Firefly / Midjourney
3. Save as `scene-001.png`, `scene-002.png` … in `images/` directory
4. Re-run without `--no-images` → images detected, generation skipped, proceeds to video

#### 5b. Voice generation (Edge TTS)

- Provider: **Microsoft Edge TTS** (free, no API key)
- Spiritual style: `en-US-ChristopherNeural`, rate `-20%`, pitch `-3Hz`
- Default English: `en-US-AndrewNeural`
- Supports 15 languages (hi, mr, es, fr, de, ja, zh, pt, ar, ru, ko, it, en-GB)

**Text preprocessing pipeline (crystal-clear audio):**
```
Raw narration
  → strip markdown headers, bold, italic, links, code, bullets
  → normalise curly quotes → straight
  → em dash → comma pause, en dash → "to"
  → ampersand → "and"
  → spiritual: preserve "..." as natural pause
  → other styles: convert "..." → period
  → collapse whitespace
  → send to TTS
```

**Word boundary timing:** Edge TTS emits `SentenceBoundary` events with exact timestamps. Words within each sentence are distributed proportionally → frame-perfect subtitle sync.

#### 5c. Subtitle generation (.srt)

- Built from word boundary events: 7 words per caption block
- Timestamps are real spoken timestamps from TTS engine (not estimated)
- Fallback: proportional estimate if boundaries unavailable (non-Edge TTS providers)

---

### 6. `video_renderer`

**File:** `src/ytfactory/agents/nodes/video_renderer.py`

- FFmpeg: `image + audio + .srt` → `scene-NNN.mp4`
- Skipped when `--no-images` was used (conditional edge routes to `END`)

---

### 7. `video_concatenator`

**File:** `src/ytfactory/agents/nodes/video_concatenator.py`

- FFmpeg concat demuxer: all `scene-NNN.mp4` → `video/final.mp4`
- Audio normalisation to YouTube's -14 LUFS target

---

## CLI Flags

```bash
ytfactory run TOPIC [OPTIONS]

Options:
  --script / -s PATH    Pre-written script file. Skips research + script-writer.
  --style TEXT          Visual style: spiritual | documentary | educational | history
  --no-images           Skip image generation. Outputs IMAGE_PROMPTS.md only.
  --project / -p ID     Resume an existing project by ID (skips project creation).
  --language / -l CODE  BCP-47 language for TTS voice (default: en).
  --auto                Skip all human-review gates (fully headless run).
```

---

## Provider Configuration (`.env`)

```env
# LLM
LLM_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.1-8b-instant    # 131,072 TPM on free tier (vs 6K for 70b)

# Search (research path only)
SEARCH_PROVIDER=tavily
TAVILY_API_KEY=...

# Image generation
IMAGE_PROVIDER=pollinations         # free, no key needed
# IMAGE_PROVIDER=gemini             # requires billing — gemini-3.1-flash-lite-image has limit:0 on free tier
# IMAGE_PROVIDER=huggingface
# IMAGE_PROVIDER=a1111              # local Automatic1111 WebUI

# TTS
TTS_PROVIDER=edge                   # free, Microsoft Edge TTS
# TTS_PROVIDER=elevenlabs

# Output resolution
IMAGE_WIDTH=1280
IMAGE_HEIGHT=720
```

### Provider matrix

| Type | Options | Free? | Notes |
|---|---|---|---|
| LLM | `groq`, `gemini`, `ollama` | Groq ✓, Gemini limited (20 req/day), Ollama local | Groq `llama-3.1-8b-instant` recommended |
| Search | `tavily` | Free tier available | Required for research path only |
| Image | `pollinations`, `huggingface`, `gemini`, `a1111` | Pollinations ✓ | Gemini image requires billing |
| TTS | `edge`, `elevenlabs` | Edge ✓ | Edge TTS has 15 language voices |

---

## Workspace Layout

```
workspace/jobs/<project-id>/
├── project.json              # stage status tracking
├── script/
│   ├── script_original.md    # raw user input (script path only)
│   └── script.md             # enhanced/generated narration script
├── scenes/
│   ├── scene-plan.json       # central artifact — consumed by all downstream stages
│   └── scene-plan.md         # human-readable scene summary
├── images/
│   ├── IMAGE_PROMPTS.md      # prompts for manual external image generation
│   ├── scene-001.png
│   └── scene-002.png …
├── audio/
│   ├── scene-001.mp3
│   └── scene-002.mp3 …
├── subtitles/
│   ├── scene-001.srt
│   └── scene-002.srt …
├── video/
│   ├── scene-001.mp4
│   ├── scene-002.mp4 …
│   └── final.mp4             # stitched final video
└── publish/
```

**All stages are idempotent** — re-running skips any file that already exists on disk.

---

## Key Design Decisions & Why

| Decision | Why |
|---|---|
| Python script splitter (no LLM for Phase 1) | Groq truncates JSON responses > ~1,200 tokens mid-stream. Python splitting is deterministic, instant, and verbatim. |
| Visual prompts batched in groups of 7 | 28 prompts in one call = truncated after scene 1. 7 × ~40 words = ~280 token output = always completes. |
| Script enhancer before scene planner | Transforms user's rough seed notes into a full cinematic narration (700-900 words) before splitting into scenes. |
| Groq `llama-3.1-8b-instant` (not 70b) | 8b-instant: 131,072 TPM free. 70b: 6,000 TPM free → causes 139s waits on multi-call pipelines. |
| `IMAGE_PROVIDER=pollinations` (not Gemini) | `gemini-3.1-flash-lite-image` has `limit: 0` on the free tier (billing required). Pollinations is truly free. |
| `--no-images` flag + END routing | Lets user skip image gen, get `IMAGE_PROMPTS.md`, generate externally (Leonardo, Firefly, Midjourney), then re-run for video. |
| TTS preprocessing strips all markdown | Edge TTS stumbles on `**bold**`, `#headers`, em dashes, curly quotes. Full strip → crystal-clear pronunciation. |
| Spiritual voice: ChristopherNeural `-20%` `-3Hz` | Slow, low-pitched male US voice. Meditative pace. Dramatic pauses at `...` preserved (Edge TTS handles them natively). |
| Sentence boundary events for subtitles | SentenceBoundary events carry real timestamps → frame-perfect subtitle sync vs LLM-estimated timing. |
| Scene stagger: `sleep(index × 3s)` | All N scenes fire simultaneously → burst rate limit 429s. Staggering spreads load across N×3 seconds. |

---

## Typical Run — Spiritual Series Video

```bash
# Step 1: Generate scene plan + audio + subtitles (skip images for now)
uv run ytfactory run "The Silent Force Controlling Your Life" \
  --script /tmp/my_spiritual_script.md \
  --style spiritual \
  --no-images \
  --auto

# Output:
#   workspace/jobs/<id>/images/IMAGE_PROMPTS.md   ← use this
#   workspace/jobs/<id>/audio/scene-001.mp3 …     ← generated
#   workspace/jobs/<id>/subtitles/scene-001.srt … ← generated

# Step 2: Generate images externally
#   → Open IMAGE_PROMPTS.md
#   → Use Leonardo AI / Adobe Firefly / Midjourney with each prompt
#   → Save as scene-001.png, scene-002.png ... in workspace/jobs/<id>/images/

# Step 3: Render video (images exist, so image gen skipped; audio exists, so TTS skipped)
uv run ytfactory run "The Silent Force Controlling Your Life" \
  --project <project-id> \
  --script /tmp/my_spiritual_script.md \
  --style spiritual \
  --auto

# Output: workspace/jobs/<id>/video/final.mp4
```

---

## Summary of Changes vs Original Pipeline

| Area | Original | Current |
|---|---|---|
| Orchestration | Sequential CLI commands | LangGraph graph with conditional routing |
| Script input | Import script only (verbatim) | `--script` flag → LLM enhancement → cinematic narration |
| Scene splitting | LLM generates full JSON (truncated on large outputs) | Python splitter (Phase 1) + batched LLM visual prompts (Phase 2) |
| Image workflow | Always auto-generate | `--no-images` flag → export prompts → manual → re-run |
| Image provider | HuggingFace FLUX | Pollinations (free, no key) with 429 backoff + stagger |
| LLM provider | Gemini (20 req/day) | Groq `llama-3.1-8b-instant` (131K TPM free) |
| TTS voice (spiritual) | Default English voice | `ChristopherNeural`, `-20%` rate, `-3Hz` pitch |
| TTS text prep | None | Full markdown strip + punctuation normalisation |
| Subtitle timing | LLM-estimated durations | Real word-boundary timestamps from Edge TTS |
| Video duration tracking | Pipeline runtime shown as "Time" | Summary shows "Estimated video: ~Xm Ys" separately |
| Parallel image calls | All at once → burst 429 | Staggered by `index × 3s` + 5-attempt backoff |
