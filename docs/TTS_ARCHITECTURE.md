# TTS Pipeline Architecture

## Overview

The TTS pipeline converts scene narration text into MP3 audio with word-level timing boundaries. It is designed for **production reliability**: validated output, automatic retry on failure, and a full debug audit trail when enabled.

```
ScenePlan.narration
        │
        ▼
 SpeechOptimizer          ← restructures written prose into spoken phrases
        │
        ▼
 SpeechFormatter          ← normalizes Unicode, strips markdown, fixes double-period bug
        │
        ▼
 TTSProvider.generate_with_boundaries()
        │
        ▼
 AudioValidator           ← verifies file size, duration, word-count ratio
        │
        ├──[pass]──▶  timing.json  +  scene-NNN.mp3
        │
        └──[fail]──▶  retry (up to tts_max_retries, exponential backoff)
```

---

## Components

### SpeechOptimizer (`providers/tts/optimizer.py`)

Restructures written narration for spoken delivery. Input is the raw narration from `scene-plan.json`. Output is a string of phrases separated by `\n\n` — each `\n\n` represents a spoken paragraph break.

The optimizer is style-aware:
- `style="spiritual"` — preserves contemplative pacing, shorter phrases, arc-aware delivery cues
- Other styles — general restructuring without style-specific tuning

The optimizer does **not** strip markdown or normalize Unicode — that is the formatter's job.

---

### SpeechFormatter (`providers/tts/formatter.py`)

Provider-independent text normalizer. Sits between optimizer and provider. All providers share the same formatter.

**Pipeline steps (in order):**

1. `strip_markdown()` — removes `**bold**`, `*italic*`, `# headings`, `[links](url)`, bullets
2. `normalize_unicode()` — converts smart quotes, em/en dashes, `…`, `&`, non-breaking spaces
3. `normalize_paragraphs()` — converts `\n\n` separators to spoken pauses
4. `normalize_punctuation()` — collapses `..`, `...`, etc. to single period
5. `collapse_whitespace()` — single-space, strip ends

**Critical fix — double-period clipping bug:**

The root cause was in the old `_prepare_text()` in `edge_tts.py`:

```python
# BUG (old code):
text = re.sub(r"\n+", ". ", text)       # "word.\n\nnext" → "word.. next"
text = re.sub(r"\.{3,}", ".", text)     # only catches 3+ periods — misses ".."
```

Edge TTS's neural model handles `..` inconsistently, occasionally clipping the first word of the phrase that follows the double period.

**Fix (`normalize_paragraphs`):**

```python
# Step A: consume trailing period before newlines (prevents double period)
text = re.sub(r"\.\s*\n+", ". ", text)  # "word.\n\nnext" → "word. next"
# Step B: handle remaining newlines (phrases without trailing period)
text = re.sub(r"\n+", ". ", text)       # "word\n\nnext" → "word. next"
```

Plus defensive `normalize_punctuation()` collapses `\.{2,}` → `.` as a catch-all.

---

### ProviderCapabilities (`providers/tts/capabilities.py`)

A frozen dataclass that advertises what a TTS provider supports. Used by pipeline code to decide which features to enable at runtime — without `isinstance` checks.

```python
caps = provider.capabilities
if caps.supports_word_boundaries:
    _, boundaries = provider.generate_with_boundaries(...)
else:
    _ = provider.generate(...)
    boundaries = []
```

| Capability | Edge TTS | ElevenLabs (future) |
|---|---|---|
| `supports_ssml` | ✗ | ✓ |
| `supports_word_boundaries` | ✓ | ✓ |
| `supports_pitch` | ✓ | ✗ |
| `supports_rate` | ✓ | ✗ |
| `supports_streaming` | ✓ | ✓ |
| `supports_emotion` | ✓ (rate/pitch) | ✗ |
| `supports_voice_styles` | ✗ | ✓ |

---

### EdgeTTSProvider (`providers/tts/edge_tts.py`)

The primary provider. Uses the `edge-tts` library to stream neural TTS from Microsoft's Edge TTS service.

**Voice selection:**

```
voice=None + language="en" + style="spiritual"  →  en-US-ChristopherNeural (documentary)
voice=None + language="hi"                      →  hi-IN-MadhurNeural
voice="custom-voice-name"                       →  custom-voice-name (any language)
```

**Emotion-aware prosody (`providers/tts/emotion.py`):**

For `style="spiritual"`, each scene is classified into one of 12 emotions (curiosity, wonder, reflection, mystery, peace, hope, compassion, urgency, sadness, awe, determination, revelation) using a keyword lexicon + structural signals (sentence-ending `?`, `!`, short sentences). The classifier applies a light "emotional arc" bias: beginning scenes lean curious, ending scenes lean hopeful.

Each emotion maps to a `rate` (+/- percentage) and `pitch` (Hz offset) passed to Edge TTS. Example:

| Emotion | Rate | Pitch |
|---|---|---|
| Curiosity | -3% | +1Hz |
| Mystery | -12% | -3Hz |
| Revelation | -15% | -2Hz |
| Urgency | +5% | +2Hz |

`pre_pause_ms` / `post_pause_ms` on `EmotionProfile` are reserved for future SSML `<break/>` injection. Edge TTS currently strips SSML tags, so these fields are defined but not wired.

**Word boundary timing:**

Edge TTS emits `SentenceBoundary` events with offset and duration in 100-nanosecond ticks. The provider converts these to per-word boundaries by distributing sentence duration proportionally across the words in each sentence.

```python
# SentenceBoundary event → per-word boundaries
for word in sentence.split():
    boundaries.append({"word": word, "start": ..., "end": ...})
```

These boundaries drive SRT caption generation (frame-perfect sync).

---

### AudioValidator (`providers/tts/validator.py`)

Validates every generated audio file before it is accepted. Duration is measured via `ffprobe` (always available in this pipeline) with `mutagen` as fallback.

**Checks:**

| Check | Threshold | Action on failure |
|---|---|---|
| File exists | — | `issues` → retry |
| File size | ≥ 1024 bytes | `issues` → retry |
| Duration measurable | > 0s | `issues` → retry |
| Minimum duration | ≥ 0.5s | `issues` → retry |
| Duration / word ratio (min) | ≥ 0.25 s/word | `issues` → retry |
| Duration / word ratio (max) | ≤ 3.0 s/word | `warnings` (non-blocking) |

`ValidationResult.passed` is `True` only when `issues` is empty.

---

### TTSDebugWriter (`providers/tts/debug.py`)

Per-scene debug file writer. When `TTS_DEBUG=true`, writes a full audit trail to `workspace/jobs/<project-id>/tts-debug/scene-NNN/`:

```
tts-debug/
├── TTS_DIAGNOSTICS.md         ← project-level summary (all scenes)
└── scene-001/
    ├── original.txt           ← raw narration from scene-plan.json
    ├── optimized.txt          ← after SpeechOptimizer
    ├── formatted.txt          ← after SpeechFormatter (= payload sent to TTS)
    ├── provider_request.json  ← exact parameters sent to TTS API
    ├── provider_response.json ← raw boundary events from provider
    ├── metadata.json          ← voice, rate, pitch, duration, retry_count, etc.
    ├── timing.json            ← word-level boundaries (seconds)
    └── validation.json        ← AudioValidator result
```

When `TTS_DEBUG=false`, all methods are no-ops — zero overhead.

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `TTS_PROVIDER` | `edge` | Provider: `edge` (or `elevenlabs` — not yet implemented) |
| `TTS_DEBUG` | `false` | Write per-scene debug files |
| `TTS_VALIDATE_AUDIO` | `true` | Validate every generated audio clip |
| `TTS_AUTO_RETRY` | `true` | Retry synthesis on validation failure |
| `TTS_MAX_RETRIES` | `3` | Max retry attempts per scene |

---

## Retry Strategy

When `TTS_AUTO_RETRY=true` and validation fails, the pipeline retries with exponential backoff:

- Attempt 1: immediate
- Attempt 2: 2s delay
- Attempt 3: 4s delay
- (Attempt N: 2^(N-1) seconds)

If all retries fail, the last generated file is kept and the pipeline continues. A warning is logged. The failure is recorded in `TTS_DIAGNOSTICS.md` when debug mode is on.

---

## Adding a New Provider

1. Create `src/ytfactory/providers/tts/<name>.py` implementing `TTSProvider`
2. Implement the `capabilities` property with accurate `ProviderCapabilities`
3. Implement `generate()` and optionally override `generate_with_boundaries()`
4. Add a `case "<name>":` in `providers/tts/factory.py`
5. Add `<NAME>_API_KEY` to `Settings` if needed

The `SpeechFormatter` is already provider-independent — the new provider receives clean, normalized text with no double periods or markdown.

---

## Debug Mode Guide

### Enable debug mode

```bash
# .env
TTS_DEBUG=true
```

Or per-run:

```bash
TTS_DEBUG=true uv run ytfactory generate-voice <project-id>
```

### Diagnose first-word clipping

1. Enable debug mode and re-run voice generation
2. Open `tts-debug/scene-NNN/formatted.txt`
3. Search for `..` (double period) — if present, the bug has not been fixed for that input
4. Compare `optimized.txt` and `formatted.txt` to see what the formatter changed
5. Check `validation.json` for any `issues`

### Diagnose truncated audio

1. Check `validation.json` → look for `duration too short` in `issues`
2. Check `provider_request.json` → verify the text was not empty
3. Check `metadata.json` → check `retry_count` to see if retries were exhausted

### Diagnose wrong voice / prosody

1. Check `metadata.json` → `voice`, `rate`, `pitch`, `emotion`
2. Verify `style` and `language` are as expected
3. For non-English, check that the language code matches a voice in `_VOICES` in `edge_tts.py`

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| First word of scene is soft/clipped | Double period in formatted text | Enable debug, check `formatted.txt` for `..` |
| Audio file too small | Edge TTS connection dropped | Check network; retry will handle it |
| All scenes silent | Wrong voice for language | Check `language` setting and `_VOICES` map |
| Captions out of sync | `generate_with_boundaries` returned empty | Provider fell back to proportional timing; check logs |
| Validation warning: long duration | Scene narration is very short | Ignore warning or reduce `_MAX_SECONDS_PER_WORD` threshold |
