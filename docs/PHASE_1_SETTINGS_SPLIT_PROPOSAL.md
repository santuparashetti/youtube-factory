# Phase 1 Step 1: Settings Split Audit & Proposal

**Date:** 2026-07-12
**Scope:** `src/ytfactory/config/settings.py` — 117 fields, 66 consumer files
**Goal:** Split into `video_core.config.SharedSettings` (generic) + `ytfactory.config.Settings` (factory-specific) to resolve the two known Bucket-C layering violations.
**Status:** Investigation + proposal only. No files created, no fields moved.

---

## Step 1 — Field Inventory (117 total fields)

### Shared → `video_core.config.SharedSettings` (27 fields)

These are the fields actively accessed by `video_core` providers today. Moving them resolves all 15 Bucket-C violations (the `from ytfactory.config.settings import Settings` imports in `video_core/`).

| Field | Type | Default | Rationale |
|---|---|---|---|
| `gemini_api_key` | str | `""` | API key |
| `tavily_api_key` | str | `""` | API key |
| `hf_token` | str | `""` | API key |
| `groq_api_key` | str | `""` | API key |
| `anthropic_api_key` | str | `""` | API key |
| `anthropic_base_url` | str | `"https://litellm.smarthubai.net"` | API endpoint — accessed by `OpenAIProvider` |
| `kokoro_api_key` | str | `""` | API key — belongs with other keys even though no video_core code reads it yet |
| `llm_provider` | str | `"anthropic"` | Provider selector — `llm/factory.py` dispatches on it |
| `search_provider` | str | `"tavily"` | Provider selector — `search/factory.py` dispatches on it |
| `tts_provider` | str | `"kokoro"` | Provider selector — `tts/factory.py` dispatches on it |
| `image_provider` | str | `"huggingface"` | Provider selector — `image/factory.py` dispatches on it |
| `gemini_text_model` | str | `"gemini-2.5-flash"` | Model name — accessed by `GeminiProvider` |
| `gemini_image_model` | str | `"gemini-3.1-flash-lite-image"` | Model name — accessed by `GeminiImageProvider` |
| `hf_image_model` | str | `"black-forest-labs/FLUX.1-schnell"` | Model name — accessed by `HuggingFaceImageProvider` |
| `groq_model` | str | `"llama-3.1-8b-instant"` | Model name — accessed by `GroqProvider` |
| `anthropic_model` | str | `"claude-haiku-4-5"` | Model name — accessed by `OpenAIProvider` |
| `ollama_base_url` | str | `"http://localhost:11434"` | Endpoint — accessed by `OllamaProvider` |
| `ollama_model` | str | `"llama3.2"` | Model name — accessed by `OllamaProvider` |
| `a1111_base_url` | str | `"http://localhost:7860"` | Endpoint — accessed by `A1111Provider` |
| `a1111_steps` | int | `30` | Provider config — accessed by `A1111Provider` |
| `a1111_cfg_scale` | float | `7.0` | Provider config — accessed by `A1111Provider` |
| `a1111_sampler` | str | `"DPM++ 2M Karras"` | Provider config — accessed by `A1111Provider` |
| `kokoro_voice` | str | `"am_michael"` | Provider config — accessed by `KokoroProvider` |
| `kokoro_speed` | float | `0.85` | Provider config — accessed by `KokoroProvider` |
| `kokoro_sample_rate` | int | `24000` | Provider config — accessed by `KokoroProvider` |
| `tts_auto_retry` | bool | `True` | Retry control — accessed by `KokoroProvider` (`kokoro.py:199`) |
| `tts_max_retries` | int | `3` | Retry control — accessed by `KokoroProvider` (`kokoro.py:199`) |

### Factory-specific → stay in `ytfactory.config.Settings` (82 fields)

Every field below is accessed exclusively from `ytfactory/` code, never `video_core/`.

| Group | Fields |
|---|---|
| Image dimensions | `image_width`, `image_height` |
| Video dimensions | `video_width`, `video_height`, `video_fps` |
| Render profile | `render_profile` |
| Subtitle pipeline (6) | `subtitle_debug`, `subtitle_validate`, `subtitle_max_cps`, `subtitle_max_chars_per_line`, `subtitle_max_lines`, `subtitle_format` |
| ASS subtitle style (17) | `subtitle_ass_theme`, `subtitle_ass_font`, `subtitle_ass_font_size`, `subtitle_ass_bold`, `subtitle_ass_italic`, `subtitle_ass_primary_color`, `subtitle_ass_outline_color`, `subtitle_ass_back_color`, `subtitle_ass_outline`, `subtitle_ass_shadow`, `subtitle_ass_margin_l`, `subtitle_ass_margin_r`, `subtitle_ass_margin_v`, `subtitle_ass_alignment`, `subtitle_ass_border_style`, `subtitle_ass_play_res_x`, `subtitle_ass_play_res_y` |
| Subtitle tail | `subtitle_tail_extension_seconds` |
| Subtitle editor V2 (5) | `subtitle_editor_enabled`, `subtitle_editor_provider`, `subtitle_editor_max_passes`, `subtitle_editor_pass_threshold`, `subtitle_editor_max_retries` |
| Subtitle segmentation | `subtitle_segmentation_mode`, `subtitle_target_cps` |
| Image prompt debug | `image_prompt_debug` |
| Human quality validation | `image_human_max_retries`, `image_human_min_sharpness` |
| TTS debug/validate | `tts_debug`, `tts_validate_audio` (lean Factory — see Ambiguous) |
| Contemplative Pacing Engine | `tts_pacing_enabled`, `tts_pacing_profile` |
| Video encoding FFmpeg (5) | `video_crf`, `video_preset`, `video_tune`, `video_keyframe_interval`, `video_audio_bitrate` |
| BGM (25) | `bgm_enabled`, `bgm_category`, `bgm_library_path`, `bgm_volume`, `bgm_duck_floor`, `bgm_duck_threshold`, `bgm_duck_ratio`, `bgm_duck_attack_ms`, `bgm_duck_release_ms`, `bgm_fade_in_seconds`, `bgm_fade_out_seconds`, `bgm_crossfade_seconds`, `bgm_random_track`, `bgm_vad_enabled`, `bgm_vad_provider`, `bgm_phrase_gap_ms`, `bgm_long_silence_ms`, `bgm_dynamic_ducking`, `bgm_restore_curve`, `bgm_adaptive_mixing`, `bgm_hold_after_speech_ms`, `bgm_long_silence_threshold_ms`, `bgm_narration_level_lufs`, `bgm_music_level_lufs`, `bgm_transition_curve` |
| Cinematic intro | `video_intro_enabled`, `video_intro_seconds` |
| WhisperX | `whisperx_enabled`, `whisperx_model`, `whisperx_device` (lean Factory — see Ambiguous) |
| Image review vision gate (8) | `image_review_enabled`, `vision_review_provider`, `vision_review_local_model`, `image_review_min_score`, `image_review_confidence`, `image_review_max_attempts`, `image_review_auto_remediate`, `image_review_debug` |
| CTA | `cta_max_retries` |
| Runtime | `request_timeout` (dead — see Ambiguous) |

### Ambiguous — flagged for explicit decision (8 fields)

| Field | Call sites | Why ambiguous | Recommendation |
|---|---|---|---|
| `tts_debug` | 3 — all in `ytfactory/voice/` | Generic TTS concept (any pipeline might want TTS debug), but currently no video_core code accesses it | **Lean Factory.** Debug mode for ytfactory's voice pipeline, not the provider. |
| `tts_validate_audio` | 2 — all in `ytfactory/voice/` | Same as `tts_debug` | **Lean Factory.** |
| `whisperx_enabled` | 2 — all in `ytfactory/` | WhisperX is a generic forced-aligner; a second factory might configure it differently | **Lean Factory.** YT's VoicePipeline owns this decision. |
| `whisperx_device` | 1 — `ytfactory/voice/pipeline.py` | Same reasoning as `whisperx_enabled` | **Lean Factory.** |
| `video_crf`, `video_preset`, `video_tune`, `video_keyframe_interval`, `video_audio_bitrate` | 2–4 each — all in `ytfactory/video/ffmpeg.py` | Generic FFmpeg concept that any video factory would configure, but comments explicitly say "for near-static slideshow content" — values are YT-workload-tuned | **Lean Factory.** Values are not portable; a podcast factory would set completely different CRF/preset. |
| `kokoro_language` | 0 anywhere | Declared but never read anywhere in `src/` or `tests/` | **Dead field. Remove in a cleanup pass.** |
| `whisperx_model` | 0 anywhere | Declared but never read anywhere | **Dead field. Remove in a cleanup pass.** |
| `request_timeout` | 0 anywhere | Declared but never read anywhere | **Dead field. Remove in a cleanup pass.** |

---

## Step 2 — Blast Radius

- **66 files** reference `settings.` or `Settings()` across `src/` + `tests/`
- **15 files in `video_core/`** import `from ytfactory.config.settings import Settings` — these are the Bucket-C violations. Every one of them accesses only the 27 Shared fields listed above:

  ```
  video_core/providers/tts/edge_tts.py
  video_core/providers/image/a1111.py
  video_core/providers/image/huggingface.py
  video_core/providers/llm/groq_provider.py
  video_core/providers/image/factory.py
  video_core/providers/image/gemini.py
  video_core/providers/llm/openai_provider.py
  video_core/providers/search/factory.py
  video_core/providers/llm/factory.py
  video_core/providers/llm/gemini.py
  video_core/providers/search/tavily.py
  video_core/providers/tts/kokoro.py
  video_core/providers/tts/factory.py
  video_core/providers/image/pollinations.py
  video_core/providers/llm/ollama.py
  ```

- **51 files in `ytfactory/` + tests** — zero import path changes needed; they continue receiving a `Settings()` instance, which IS a `SharedSettings` instance via inheritance.

- **`edge_tts.py` and `pollinations.py` special case:** both store `self._settings = settings` in `__init__` but never call `self._settings.<field>` anywhere. Their `Settings` type annotation is purely cosmetic. Changing it to `SharedSettings` is a 1-line annotation change with zero logic impact.

---

## Step 3 — Proposed Split Shape

### Class hierarchy

```python
# src/video_core/config/shared_settings.py  (NEW FILE)
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class SharedSettings(BaseSettings):
    """Shared configuration — API keys, provider selectors, model names.
    Any factory built on video_core can extend this."""

    # API keys
    gemini_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")
    hf_token: str = Field(default="")
    groq_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    anthropic_base_url: str = Field(default="https://litellm.smarthubai.net")
    kokoro_api_key: str = Field(default="")

    # Provider selectors
    llm_provider: str = "anthropic"
    search_provider: str = "tavily"
    tts_provider: str = "kokoro"
    image_provider: str = "huggingface"

    # LLM model names
    gemini_text_model: str = "gemini-2.5-flash"
    hf_image_model: str = "black-forest-labs/FLUX.1-schnell"
    groq_model: str = "llama-3.1-8b-instant"
    anthropic_model: str = "claude-haiku-4-5"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # Image model names
    gemini_image_model: str = "gemini-3.1-flash-lite-image"

    # A1111 / SD WebUI provider config
    a1111_base_url: str = "http://localhost:7860"
    a1111_steps: int = 30
    a1111_cfg_scale: float = 7.0
    a1111_sampler: str = "DPM++ 2M Karras"

    # Kokoro TTS provider config
    kokoro_voice: str = "am_michael"
    kokoro_speed: float = 0.85
    kokoro_sample_rate: int = 24000

    # TTS retry control (accessed by KokoroProvider in video_core)
    tts_auto_retry: bool = True
    tts_max_retries: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# src/ytfactory/config/settings.py  (MODIFIED — add inheritance, move 27 fields out)
class Settings(SharedSettings):
    """ytfactory-specific configuration — extends SharedSettings with
    pipeline, quality, and content-specific settings."""

    # All 82 (or 90 with lean-Factory ambiguous) factory-specific fields remain here.
    # model_config can be omitted (inherited) or kept identical — both work.
```

### Why inheritance is viable

1. **All 51 ytfactory call sites: zero changes.** A `Settings()` instance is a `SharedSettings` instance. `settings.gemini_api_key`, `settings.bgm_enabled`, etc. all resolve via normal Python MRO — declared in the base or child, the attribute lookup is identical.

2. **15 video_core files: import + type annotation only.** Each changes:
   ```python
   # before
   from ytfactory.config.settings import Settings
   def __init__(self, settings: Settings): ...

   # after
   from video_core.config.shared_settings import SharedSettings
   def __init__(self, settings: SharedSettings): ...
   ```
   No logic changes. No field access changes. Callers already pass `Settings()` instances, which are valid `SharedSettings` instances.

3. **Instantiation pattern: per-call, not singleton.** Most code does `settings = Settings()` at the point of use. Two module-level instances exist: `agents/nodes/publish.py` `_settings = Settings()` and `agents/nodes/cta.py` `_settings = Settings()`. The inheritance split doesn't change this pattern.

4. **`.env` loading: no splitting required.** pydantic-settings resolves all fields across the full class MRO against the same `.env` file when `Settings()` is instantiated. `SharedSettings` declares `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`; `Settings` inherits it. All 117 fields continue to be populated from the single `.env` file. No per-class env files. No user-facing change.

5. **`check_layering.py` allowlist shrinks by one.** After Phase 1, `KNOWN_BUCKET_C` removes `ytfactory.config.settings`; only `ytfactory.shared.constants` remains (until Phase 2 — WORKSPACE_DIR move).

### Migration risk callouts

| Call site category | File count | Code change required |
|---|---|---|
| `ytfactory/` modules doing `settings.<field>` | ~51 files | **None** — `Settings` inherits all fields |
| `video_core/` provider files importing `Settings` | 15 files | Import line + type annotation — 2 lines each, no logic |
| `edge_tts.py`, `pollinations.py` (store but never access fields) | 2 files | Type annotation only — 1 line each |
| Tests patching `ytfactory.config.settings.Settings` | inspect before execution | Tests that instantiate video_core providers directly may need to patch `SharedSettings` instead of `Settings` — **audit test patches before executing Phase 1** |

The test patch concern is the only non-trivial risk: any test that does `patch("ytfactory.config.settings.Settings")` and passes the mock into a `video_core` provider constructor will stop working after the import path changes. These need to be identified and updated to `patch("video_core.config.shared_settings.SharedSettings")`.

---

## Summary

| Category | Count | Action |
|---|---|---|
| Shared (must move to `SharedSettings`) | 27 fields | Create `video_core/config/shared_settings.py`, move these fields |
| Factory-specific (stay in `Settings`) | 82 fields | No change |
| Ambiguous → lean Factory | 5 fields | Keep in `Settings`; note in comments they're ytfactory-specific |
| Dead fields → remove | 3 fields (`kokoro_language`, `whisperx_model`, `request_timeout`) | Delete in a cleanup pass separate from the split |
| ytfactory call sites needing changes | 0 | None — inheritance preserves all attribute paths |
| video_core files needing changes | 15 | Import path + type annotation only |
