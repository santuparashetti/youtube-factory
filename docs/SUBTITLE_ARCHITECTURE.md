# Subtitle Intelligence Engine — Architecture

## Overview

The Subtitle Intelligence Engine replaces the original fixed-word-count SRT builder with a semantic, linguistically-aware subtitle generation pipeline. It is the single source of truth for subtitle creation — both `captions/pipeline.py` and `agents/nodes/scene_assets.py` delegate to it.

```
word boundaries (TTS)
        │
        ▼
 SubtitleSegmenter        ← semantic grouping, two-line splitting
        │
        ▼
  TimingEngine            ← 4-pass repair (clamp, overlap, gap, renumber)
        │
        ▼
 SubtitleValidator        ← 6 checks; EMPTY_CUE → removed; rest are warnings
        │
        ▼
   SRTWriter              ← serialization; get_writer() for future formats
        │
        ▼
SubtitleDebugWriter       ← per-scene audit files (no-op when disabled)
```

Entry point: `SubtitleEngine.build()` or `SubtitleEngine.build_report()`.

---

## Configuration

All settings live in `config/settings.py` and map 1-to-1 to environment variables.

| Setting | Env var | Default | Description |
|---|---|---|---|
| `subtitle_debug` | `SUBTITLE_DEBUG` | `false` | Write per-scene debug files |
| `subtitle_validate` | `SUBTITLE_VALIDATE` | `true` | Run validator pass |
| `subtitle_max_cps` | `SUBTITLE_MAX_CPS` | `18.0` | Max characters per second |
| `subtitle_max_chars_per_line` | `SUBTITLE_MAX_CHARS_PER_LINE` | `42` | Max chars per display line |
| `subtitle_max_lines` | `SUBTITLE_MAX_LINES` | `2` | Max lines per cue |
| `subtitle_format` | `SUBTITLE_FORMAT` | `srt` | Output format (only SRT today) |

Use `SubtitleEngine.from_settings(settings)` to instantiate from a `Settings` object. It uses `getattr(settings, key, default)` for every attribute so it works with partial or minimal settings objects (including test stubs).

---

## Components

### `subtitles/engine.py` — `SubtitleEngine`

Orchestrator. All business logic is delegated to sub-components.

```python
engine = SubtitleEngine.from_settings(settings)

# Just the SRT string:
srt = engine.build(boundaries, narration, scene_index, project_id, total_duration)

# SRT + diagnostics report:
srt, report = engine.build_report(boundaries, narration, scene_index, project_id, total_duration)
```

When `boundaries` is empty, falls back to `SubtitleSegmenter.fallback_segment()`.

---

### `subtitles/segmenter.py` — `SubtitleSegmenter`

Converts word-level timing boundaries (`[{word, start, end}]`) into semantically grouped `SubtitleCue` objects.

**Break decision (per word, evaluated left-to-right):**

| Priority | Condition | Guard |
|---|---|---|
| FORCE | char overflow OR CPS overflow (≥3 words) | none |
| MUST | previous word ends `.!?` AND not abbreviation AND not number AND not in quotes | `len(pending) >= 2` |
| PREFER | previous word ends `,;:` AND not in quotes | `len(pending) >= 3` |
| SUPPRESS | next word would be trailing function word | overrides all |

**Protected spans:**
- Numbers/measurements: `_RE_NUMBER` matches `3.5`, `100m`, `42%`, `2,000`
- Common abbreviations: `Mr.`, `Dr.`, `Prof.`, `etc.`, months, etc. (see `_ABBREVIATIONS` frozenset)
- Quoted spans: opening `"` sets `in_quotes=True`; closing `"` clears it

**Two-line splitting** (`_split_lines`):
- Single line if `len(text) ≤ MAX_CHARS_PER_LINE`
- Otherwise: find word boundary nearest character midpoint; clause terminals get a bonus score of -2 (preferred split points); trailing function words are skipped
- Rejects the split if either resulting line exceeds `MAX_CHARS_PER_LINE`

**Fallback** (`fallback_segment`):
When no word boundaries are available, splits narration into sentences via regex `(?<=[.!?])\s+(?=[A-Z])` and assigns proportional timing based on character weight.

---

### `subtitles/typography.py` — `SubtitleTypographer`

Display-facing text normalization. Applied to each cue's lines during segmentation.

**Pipeline (in order):**
1. `normalize_quotes` — smart/curly quotes → straight ASCII
2. `normalize_dashes` — em dash `—` and en dash `–` → ` - ` (subtitle boxes are narrow)
3. `normalize_ellipsis` — Unicode `…` → `...` (**kept** for display — different from `SpeechFormatter` which removes it)
4. `repair_punctuation` — fixes `,.`, `?.`, `!.`, `;.`, `:.`, `....+`, ` ,`
5. `normalize_spaces` — collapse multiple spaces, strip leading/trailing
6. `capitalize_first` — ensure first character of each cue is uppercase

**Key difference from `SpeechFormatter`:** The `...` ellipsis is preserved for visual display (subtitle readers expect to see it). `SpeechFormatter` collapses it to a pause cue for TTS synthesis.

---

### `subtitles/timing.py` — `TimingEngine`

4-pass repair applied after initial segmentation.

| Pass | Action |
|---|---|
| 1. `clamp_duration` | Clamp each cue to `[_MIN_DURATION=0.5s, _MAX_DURATION=7.0s]` |
| 2. `fix_overlaps` | If cue N end > cue N+1 start, pull cue N end back to `N+1 start - _MIN_GAP=0.04s` |
| 3. `close_gaps` | If gap between cues < `_GAP_CLOSE_THRESHOLD=0.15s`, extend prior cue end; cap extension at `_GAP_CLOSE_MAX=0.40s` |
| 4. `renumber` | Reindex all cues 1..N sequentially |

Returns `(cues, (overlap_repair_count, gap_repair_count))` for diagnostics.

---

### `subtitles/validator.py` — `SubtitleValidator`

Post-timing validation pass. Runs only when `subtitle_validate=true`.

| Code | Severity | Action |
|---|---|---|
| `EMPTY_CUE` | error | Cue removed entirely |
| `SHORT_DUR` | warning | Flagged only |
| `LONG_DUR` | warning | Flagged only |
| `HIGH_CPS` | warning | Flagged only |
| `LONG_LINE` | warning | Flagged only |
| `ORPHAN` | warning | Single-word line flagged |

Returns `(repaired_cues, issues)`. `EMPTY_CUE` is the only auto-repair (removal). Other findings are non-destructive warnings.

---

### `subtitles/writer.py` — `SRTWriter` + `get_writer()`

Format-agnostic serialization layer.

```python
writer = get_writer(SubtitleFormat.SRT)   # or get_writer("srt")
srt_string = writer.write(cues)
```

`get_writer()` raises `ValueError` for unsupported formats — no silent fallback.

`_fmt_srt_time(seconds)` handles:
- Scenes longer than 59 seconds (uses `h = int(seconds // 3600)`)
- Millisecond rounding artifacts (clamps ms to 999 max)

**To add WebVTT:** implement `WebVTTWriter` with same `write(cues) -> str` signature, add `WEBVTT = "webvtt"` to `SubtitleFormat`, add a `case` in `get_writer()`.

---

### `subtitles/debug.py` — `SubtitleDebugWriter`

Per-scene and per-project audit trail. All methods are no-ops when `enabled=False` — zero overhead in production.

**Per-scene directory:** `workspace/jobs/<project-id>/subtitle-debug/scene-NNN/`

| File | Contents |
|---|---|
| `subtitle-original.txt` | Raw narration text |
| `subtitle-optimized.txt` | Typography-cleaned narration |
| `subtitle-word-boundaries.json` | Raw word boundaries from TTS |
| `subtitle-final.srt` | Final SRT output |
| `subtitle-analysis.json` | SubtitleReport.to_dict() |
| `subtitle-validation.json` | All ValidationIssue objects |

**Project-level summary:** `workspace/jobs/<project-id>/SUBTITLE_DIAGNOSTICS.md`
Written by `SubtitleDebugWriter.write_project_summary(project_id, reports)` after all scenes complete.

---

### `subtitles/models.py` — Domain Types

```python
class SubtitleFormat(str, Enum):
    SRT = "srt"

@dataclass
class SubtitleCue:
    index: int; start: float; end: float; lines: list[str]
    # Computed: text, duration, char_count, cps, longest_line

@dataclass
class ValidationIssue:
    cue_index: int; code: str; severity: str; message: str; repaired: bool

@dataclass
class SubtitleReport:
    scene_index: int; cue_count: int; avg_cps: float; max_cps: float
    avg_duration: float; min_duration: float; max_duration: float
    overlap_repairs: int; gap_repairs: int; typography_repairs: int
    issues: list[ValidationIssue]
    def to_dict(self) -> dict: ...
```

---

## Integration Points

### `captions/pipeline.py`

Replaces `_boundaries_to_srt()`, `_fallback_srt()`, `_ts()`, `_WORDS_PER_LINE` (all deleted).

```python
engine = SubtitleEngine.from_settings(settings)
srt, report = engine.build_report(boundaries, narration, scene_index, project_id, audio_duration)
```

### `agents/nodes/scene_assets.py`

Same delegation pattern. `_get_audio_duration()` delegates to `AudioValidator._measure_duration`.

---

## Testing

```bash
uv run pytest tests/subtitles/ -v
```

| Test file | Coverage |
|---|---|
| `test_typography.py` | 22 tests — all 6 normalization steps |
| `test_segmenter.py` | 17 tests — breaks, protected spans, fallback, typography integration |
| `test_timing.py` | 12 tests — each repair pass, edge cases |
| `test_writer.py` | 11 tests — SRT format, timestamp overflow, empty input |
| `test_engine.py` | 14 tests — full pipeline, `from_settings`, documentary smoke test |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Subtitles break in the middle of a sentence | `must_break` firing on abbreviation period | Check `_ABBREVIATIONS` frozenset; add missing abbreviation |
| Very long single cues | CPS guard not triggering | Lower `SUBTITLE_MAX_CPS`; or narration words are slow-paced |
| Subtitle lines > 42 chars | `_split_lines` couldn't find a valid split | Two-line split falls back to single-line when no valid split exists; accept or reduce `SUBTITLE_MAX_CHARS_PER_LINE` |
| `ORPHAN` warnings in diagnostics | Short clause isolated on its own line | Expected for short interjections; not auto-repaired |
| Empty SRT output | No word boundaries AND empty narration | Check that TTS pipeline ran and `scene-NNN.mp3` exists before captions stage |
| `SHORT_DUR` warnings | Audio very short or TTS boundaries dense | TimingEngine will clamp to 0.5s minimum; warnings are informational |

---

## Design Constraints

- **No LLM calls** — entire pipeline is deterministic pure Python
- **O(n)** in number of word boundaries
- **No external dependencies** beyond the existing codebase — no NLTK, spaCy, or regex libraries beyond stdlib `re`
- **Zero overhead when disabled** — `SubtitleDebugWriter` and `SubtitleValidator` both short-circuit when their flags are off
- **Idempotent** — `captions/pipeline.py` skips scenes where output already exists
