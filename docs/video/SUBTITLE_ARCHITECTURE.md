# Subtitle Intelligence Engine — Architecture

## Overview

The Subtitle Intelligence Engine replaces the original fixed-word-count SRT builder with a semantic, linguistically-aware subtitle generation pipeline. ASS (Advanced SubStation Alpha) is the primary output format, with SRT generated alongside for compatibility and debug. Both `captions/pipeline.py` and `agents/nodes/scene_assets.py` delegate to a single orchestrator.

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
        ├──── ASSWriter  ← primary output: styled .ass file
        │         ▲
        │    ThemeManager + ASSTheme + ASSStyleBuilder
        │
        ├──── SRTWriter  ← compatibility .srt file (always generated)
        │
        ▼
SubtitleDebugWriter       ← per-scene audit files (no-op when disabled)
```

Entry points:
- `SubtitleEngine.build()` → SRT string (backward-compatible)
- `SubtitleEngine.build_both()` → `(ass, srt, report)` — primary path when `subtitle_format=ass`
- `SubtitleEngine.build_report()` → `(srt, report)`

---

## ASS Subtitle Engine

### What is ASS?

Advanced SubStation Alpha (`.ass`) is a professional subtitle format that supports rich styling: fonts, colors, outlines, shadows, margins, per-style positioning, and future extensions (karaoke, animations). FFmpeg's `subtitles` filter renders ASS styling when burning in subtitles — giving documentary-quality text on YouTube.

### ASS File Structure

```
[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, ...
Style: Default,Arial,52,&H00FFFFFF,&H00FFFF00,&H00000000,&H80000000,-1,0,...

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,In the ancient forest\NLight barely reached below.
```

Key ASS specifics:
- **Colors**: `&HAABBGGRR` (reversed from RGB; AA=00 is opaque, FF is transparent)
- **Multi-line**: `\N` hard line break
- **Timestamps**: `H:MM:SS.cc` (centiseconds, not milliseconds)
- **Bold flag**: `-1` = bold, `0` = not bold

### Module: `subtitles/ass/`

| File | Class | Role |
|---|---|---|
| `theme.py` | `ASSTheme` | Frozen dataclass holding all style parameters |
| `theme_manager.py` | `ThemeManager` | Built-in themes + settings-driven customization |
| `style_builder.py` | `ASSStyleBuilder` | Generates [V4+ Styles] section |
| `writer.py` | `ASSWriter` | Produces complete .ass file from cues + theme |

### Built-in Themes

| Theme | Description |
|---|---|
| `default` | White text, black outline, 52px Arial Bold, 50% shadow. Documentary standard. |
| `minimal` | Thinner outline, no shadow. Cleaner on light backgrounds. |
| `high_contrast` | 58px, thick outline, opaque box. Accessibility / small screen. |
| `cinematic` | Georgia italic, softer shadow, higher margin. Film aesthetic. |

### Future-ready Extension Points

- **Multiple styles**: `ASSStyleBuilder.build_section(base, extra_themes=[speaker_theme])` — pass named styles for per-speaker subtitles
- **Karaoke**: Add ASS `\k` timing tags per word inside `_dialogue_line()`
- **Animations**: Add `\fad(ms_in,ms_out)` or `\move(x1,y1,x2,y2)` override tags
- **Word highlighting**: Inject `\1c&Hcolor&` per-word tags in future `build_karaoke()`

---

## Configuration

All settings live in `config/settings.py` and map 1-to-1 to environment variables.

### Core settings

| Setting | Env var | Default | Description |
|---|---|---|---|
| `subtitle_debug` | `SUBTITLE_DEBUG` | `false` | Write per-scene debug files |
| `subtitle_validate` | `SUBTITLE_VALIDATE` | `true` | Run validator pass |
| `subtitle_max_cps` | `SUBTITLE_MAX_CPS` | `18.0` | Max characters per second |
| `subtitle_max_chars_per_line` | `SUBTITLE_MAX_CHARS_PER_LINE` | `42` | Max chars per display line |
| `subtitle_max_lines` | `SUBTITLE_MAX_LINES` | `2` | Max lines per cue |
| `subtitle_format` | `SUBTITLE_FORMAT` | `ass` | Primary output format (`ass` or `srt`) |

### ASS styling settings

| Setting | Env var | Default | Description |
|---|---|---|---|
| `subtitle_ass_theme` | `SUBTITLE_ASS_THEME` | `default` | Theme preset name |
| `subtitle_ass_font` | `SUBTITLE_ASS_FONT` | `Arial` | Font family |
| `subtitle_ass_font_size` | `SUBTITLE_ASS_FONT_SIZE` | `52` | Font size in pixels (1920×1080) |
| `subtitle_ass_bold` | `SUBTITLE_ASS_BOLD` | `true` | Bold text |
| `subtitle_ass_italic` | `SUBTITLE_ASS_ITALIC` | `false` | Italic text |
| `subtitle_ass_primary_color` | `SUBTITLE_ASS_PRIMARY_COLOR` | `&H00FFFFFF` | Text color (white) |
| `subtitle_ass_outline_color` | `SUBTITLE_ASS_OUTLINE_COLOR` | `&H00000000` | Outline color (black) |
| `subtitle_ass_back_color` | `SUBTITLE_ASS_BACK_COLOR` | `&H80000000` | Shadow/box color (50% transparent black) |
| `subtitle_ass_outline` | `SUBTITLE_ASS_OUTLINE` | `2.0` | Outline thickness |
| `subtitle_ass_shadow` | `SUBTITLE_ASS_SHADOW` | `1.0` | Shadow depth |
| `subtitle_ass_margin_l` | `SUBTITLE_ASS_MARGIN_L` | `80` | Left safe margin (px) |
| `subtitle_ass_margin_r` | `SUBTITLE_ASS_MARGIN_R` | `80` | Right safe margin (px) |
| `subtitle_ass_margin_v` | `SUBTITLE_ASS_MARGIN_V` | `60` | Vertical margin from bottom (px) |
| `subtitle_ass_alignment` | `SUBTITLE_ASS_ALIGNMENT` | `2` | Numpad alignment (2=bottom-center) |
| `subtitle_ass_border_style` | `SUBTITLE_ASS_BORDER_STYLE` | `1` | 1=outline+shadow, 3=opaque box |
| `subtitle_ass_play_res_x` | `SUBTITLE_ASS_PLAY_RES_X` | `1920` | Script resolution width |
| `subtitle_ass_play_res_y` | `SUBTITLE_ASS_PLAY_RES_Y` | `1080` | Script resolution height |

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

When `subtitle_format="ass"` (default):
```python
engine = SubtitleEngine.from_settings(settings)
ass, srt, report = engine.build_both(boundaries, narration, scene_index, project_id, audio_duration)
ass_path.write_text(ass)   # scene-001.ass — primary for rendering
srt_path.write_text(srt)   # scene-001.srt — compat/debug
```

When `subtitle_format="srt"` (backward compat):
```python
srt, report = engine.build_report(boundaries, narration, scene_index, project_id, audio_duration)
srt_path.write_text(srt)
```

### `agents/nodes/scene_assets.py`

Same dual-format delegation. `_get_audio_duration()` delegates to `AudioValidator._measure_duration`.

### `video/pipeline.py`

Prefers `.ass` for rendering when it exists, falls back to `.srt`:
```python
ass_sub = project_dir / "subtitles" / f"scene-{index:03d}.ass"
srt_sub = project_dir / "subtitles" / f"scene-{index:03d}.srt"
subtitle = ass_sub if ass_sub.exists() else srt_sub
```

FFmpeg's `subtitles` filter automatically handles both formats.

### `captions/models.py` — `CaptionArtifact`

```python
artifact = CaptionArtifact(scene_id=1, srt_path=srt_path, ass_path=ass_path)
artifact.primary_path  # → ass_path if exists, else srt_path
```

---

## Testing

```bash
uv run pytest tests/subtitles/ -v
```

| Test file | Coverage |
|---|---|
| `test_typography.py` | 22 tests — all 6 normalization steps |
| `test_segmenter.py` | 16 tests — breaks, protected spans, fallback, typography integration |
| `test_timing.py` | 12 tests — each repair pass, edge cases |
| `test_writer.py` | 11 tests — SRT format, timestamp overflow, empty input |
| `test_engine.py` | 14 tests — full pipeline, `from_settings`, documentary smoke test |
| `test_ass_theme.py` | 26 tests — ASSTheme fields, flags, ThemeManager, settings overrides |
| `test_ass_writer.py` | 32 tests — timestamps, sections, dialogue, multi-line, custom themes |
| `test_ass_integration.py` | 36 tests — SubtitleFormat enum, get_writer factory, build_both, from_settings, smoke test |

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
