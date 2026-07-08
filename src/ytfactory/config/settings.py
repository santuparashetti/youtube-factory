from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------

    gemini_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")
    hf_token: str = Field(default="")
    groq_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    anthropic_base_url: str = Field(default="https://api.anthropic.com")

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    llm_provider: str = "gemini"
    search_provider: str = "tavily"
    tts_provider: str = "edge"
    image_provider: str = "pollinations"

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    gemini_text_model: str = "gemini-2.5-flash"
    gemini_image_model: str = "gemini-3.1-flash-image"

    hf_image_model: str = "black-forest-labs/FLUX.1-schnell"

    groq_model: str = "llama-3.1-8b-instant"
    anthropic_model: str = "claude-haiku-4-5"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"

    # Automatic1111 / SD WebUI
    a1111_base_url: str = "http://localhost:7860"
    a1111_steps: int = 30
    a1111_cfg_scale: float = 7.0
    a1111_sampler: str = "DPM++ 2M Karras"

    # ------------------------------------------------------------------
    # Image Defaults
    # ------------------------------------------------------------------

    # Native YouTube Full HD
    image_width: int = 1920
    image_height: int = 1080

    # ------------------------------------------------------------------
    # Video Defaults
    # ------------------------------------------------------------------

    video_width: int = 1920
    video_height: int = 1080
    video_fps: int = 30

    # ------------------------------------------------------------------
    # Rendering Profile
    # ------------------------------------------------------------------

    # Cinematic quality level applied by MotionPlanner and TransitionPlanner.
    # draft    — static frame, hard cuts (fastest render, no motion)
    # balanced — simple zoom/pan, cross-dissolves (default)
    # cinematic — full emotion-aware motion + transitions, ease_in_out
    # premium   — wider scale ranges, longer fades
    render_profile: str = "balanced"

    # ------------------------------------------------------------------
    # Subtitle Intelligence Engine
    # ------------------------------------------------------------------

    # Write per-scene debug files to workspace/jobs/<id>/subtitle-debug/
    subtitle_debug: bool = False

    # Run validation checks on every generated subtitle
    subtitle_validate: bool = True

    # Maximum characters per second (Netflix: 17, BBC: 17, default: 18)
    subtitle_max_cps: float = 18.0

    # Maximum characters per subtitle line
    subtitle_max_chars_per_line: int = 42

    # Maximum number of display lines per subtitle cue
    subtitle_max_lines: int = 2

    # Primary output format: "ass" (default) or "srt"
    # ASS produces professional styled subtitles; SRT is always written alongside for compat.
    subtitle_format: str = "ass"

    # ------------------------------------------------------------------
    # ASS Subtitle Engine — Style Configuration
    # ------------------------------------------------------------------

    # Theme preset: "default" | "minimal" | "high_contrast" | "cinematic"
    subtitle_ass_theme: str = "default"

    # Font family (must be installed on the render machine)
    subtitle_ass_font: str = "Arial"

    # Font size in pixels at PlayResX × PlayResY (1920 × 1080)
    subtitle_ass_font_size: int = 52

    # Bold text (-1 = bold, 0 = not bold in ASS convention)
    subtitle_ass_bold: bool = True

    # Italic text
    subtitle_ass_italic: bool = False

    # ASS color format: &HAABBGGRR (alpha, blue, green, red)
    # AA: 00 = opaque, FF = transparent
    subtitle_ass_primary_color: str = "&H00FFFFFF"  # white text
    subtitle_ass_outline_color: str = "&H00000000"  # black outline
    subtitle_ass_back_color: str = "&H80000000"  # 50% transparent black shadow

    # Outline and shadow thickness in pixels
    subtitle_ass_outline: float = 2.0
    subtitle_ass_shadow: float = 1.0

    # Safe margins from the video edges in pixels (1920 × 1080 reference)
    subtitle_ass_margin_l: int = 80
    subtitle_ass_margin_r: int = 80
    subtitle_ass_margin_v: int = 60

    # Subtitle alignment (numpad layout: 2 = bottom-center)
    subtitle_ass_alignment: int = 2

    # Border style: 1 = outline + shadow, 3 = opaque box
    subtitle_ass_border_style: int = 1

    # Script resolution — must match video dimensions
    subtitle_ass_play_res_x: int = 1920
    subtitle_ass_play_res_y: int = 1080

    # Extend the last subtitle cue by this many seconds so it remains visible
    # through the fade-to-black transition at the end of each scene.
    subtitle_tail_extension_seconds: float = 1.0

    # ------------------------------------------------------------------
    # Subtitle Intelligence Editor (V2)
    # ------------------------------------------------------------------

    # Enable the LLM editorial pass after raw subtitle generation.
    # When True, SubtitleEditingEngine runs after SubtitleEngine and
    # re-writes .srt / .ass with improved punctuation, capitalisation,
    # and line breaks while preserving all timing exactly.
    subtitle_editor_enabled: bool = False

    # Subtitle editor backend: "llm" (uses the configured LLM provider)
    # or "mock" (passthrough, no API calls — useful for tests).
    subtitle_editor_provider: str = "llm"

    # Maximum editorial passes before accepting the best-scoring version.
    subtitle_editor_max_passes: int = 3

    # Quality score threshold (0–100) to stop iterating early.
    # The engine stops as soon as a pass scores >= this value.
    subtitle_editor_pass_threshold: float = 95.0

    # Maximum LLM call retries per pass on cue_id mismatch or parse error.
    subtitle_editor_max_retries: int = 3

    # ------------------------------------------------------------------
    # Image Prompt Engine V4 — Debug & Quality Control
    # ------------------------------------------------------------------

    # Write per-scene debug files to workspace/jobs/<id>/images/debug/
    # Saves scene-XXX-original.txt, scene-XXX-optimized.txt, image_prompt_debug.json
    image_prompt_debug: bool = False

    # ------------------------------------------------------------------
    # Human Quality Validation
    # ------------------------------------------------------------------

    # Maximum additional generation attempts for scenes with detected humans
    # when the generated image is below the sharpness threshold.
    # 0 = disable human-quality retry entirely.
    image_human_max_retries: int = 2

    # Minimum Pillow edge-detection stddev score to accept a human scene.
    # Images below this threshold are regenerated (up to image_human_max_retries).
    # Score reference: < 8 = blurry, 8–15 = marginal, > 15 = sharp.
    image_human_min_sharpness: float = 12.0

    # ------------------------------------------------------------------
    # TTS Debug & Quality Control
    # ------------------------------------------------------------------

    # Write intermediate text files + metadata to workspace/jobs/<id>/tts-debug/
    tts_debug: bool = False

    # Validate every generated audio clip (file size, duration, word-count ratio)
    tts_validate_audio: bool = True

    # Automatically retry synthesis when validation fails
    tts_auto_retry: bool = True

    # Maximum retry attempts per scene (exponential backoff between attempts)
    tts_max_retries: int = 3

    # ------------------------------------------------------------------
    # Contemplative Pacing Engine
    # ------------------------------------------------------------------

    # Enable sentence-level pause injection (silence gaps between sentences).
    # When True, the optimizer still applies phrase-splitting and keyword emphasis
    # per sentence; silences are injected BETWEEN sentences via FFmpeg concat.
    # Disabled automatically for scene_type=="asset" scenes.
    tts_pacing_enabled: bool = True

    # Pacing profile — controls pause duration ranges per sentence weight class.
    # Options: normal | documentary | spiritual | meditation | slow_reflection
    # "spiritual" inserts generous pauses (500–700ms normal, 1.2–1.8s important,
    # 2.0–2.5s major realization) so viewers have time to absorb each idea.
    tts_pacing_profile: str = "spiritual"

    # ------------------------------------------------------------------
    # Video Encoding — FFmpeg H.264 parameters
    # ------------------------------------------------------------------

    # H.264 Constant Rate Factor (CRF) — 0=lossless, 51=worst.
    # 23 is the H.264 default ("visually lossless" for cinematic content).
    # Lower = higher quality and larger files; 18 is overkill for YouTube.
    video_crf: int = 23

    # x264 encoder preset. Slower presets compress better for motion-heavy content,
    # but for near-static slideshow content (slow zoompan on still images) "medium"
    # is optimal — "slow"/"veryslow" add encoding time without size benefit and can
    # even produce slightly larger files due to increased lookahead overhead.
    # Options: ultrafast fast medium slow veryslow
    video_preset: str = "medium"

    # x264 tune. "film" increases PSY-RD which adds bitrate for fine-detail
    # preservation — counterproductive for AI-generated images at documentary
    # quality. Empty string disables tuning, keeping bitrate as low as possible.
    # Set to "film" for live-action photorealistic content.
    video_tune: str = ""

    # Keyframe (GOP) interval in frames. 60 = every 2 s at 30 fps.
    # Controls seek accuracy; lower = larger files, faster seeking.
    video_keyframe_interval: int = 60

    # AAC audio bitrate for the scene narration track.
    # 128k is sufficient and indistinguishable from 192k for voice content.
    video_audio_bitrate: str = "128k"

    # ------------------------------------------------------------------
    # Background Music (BGM)
    # ------------------------------------------------------------------

    # Master enable — False = no BGM (default; opt-in per project)
    bgm_enabled: bool = False

    # BGM category. "auto" selects based on video topic.
    # Options: auto | spiritual | meditation | cinematic_ambient |
    #          emotional_documentary | inspirational | calm_piano | nature_ambient
    bgm_category: str = "auto"

    # Directory containing music files.
    # Layout: <path>/<category>/*.mp3  or  <path>/*.mp3 (flat)
    bgm_library_path: str = "workspace/music"

    # BGM volume relative to full scale during quiet/pause sections (0.0–1.0).
    bgm_volume: float = 0.30

    # Minimum BGM level during active speech (0.0–bgm_volume).
    bgm_duck_floor: float = 0.04

    # Sidechain compress threshold — amplitude above which ducking engages.
    # 0.008 ≈ −42 dBFS — catches speech onset early.
    bgm_duck_threshold: float = 0.008

    # Ducking compression ratio — 8:1 for strong, clean ducking.
    bgm_duck_ratio: float = 8.0

    # Milliseconds for ducking to engage after speech onset.
    # 15 ms: near-instantaneous onset.
    bgm_duck_attack_ms: int = 15

    # Milliseconds for music to recover after speech ends.
    # 350 ms: fast recovery without audible pumping.
    bgm_duck_release_ms: int = 350

    # Music fade-in at video start (seconds).
    bgm_fade_in_seconds: float = 1.5

    # Music fade-out at video end (seconds).
    bgm_fade_out_seconds: float = 2.5

    # Crossfade between loop iterations (seconds).
    bgm_crossfade_seconds: float = 2.0

    # Randomly select from available tracks in the category.
    bgm_random_track: bool = True

    # ── BGM V2: VAD-assisted adaptive ducking ─────────────────────────────

    # Enable VAD pre-analysis for phrase grouping and debug output.
    bgm_vad_enabled: bool = True

    # VAD backend ("silero" preferred; current impl uses FFmpeg silencedetect).
    bgm_vad_provider: str = "silero"

    # Gap (ms) between speech bursts treated as a single continuous phrase.
    bgm_phrase_gap_ms: int = 300

    # Silence duration (ms) after which music recovers to full volume.
    bgm_long_silence_ms: int = 2000

    # Vary duck depth with narration energy (louder → deeper duck).
    bgm_dynamic_ducking: bool = True

    # Volume recovery curve after long silence ("logarithmic" matches compressor).
    bgm_restore_curve: str = "logarithmic"

    # ------------------------------------------------------------------
    # Cinematic Intro
    # ------------------------------------------------------------------

    # Prepend a silent black screen before Scene 1 in the final video.
    # Intentional cinematic pause — does NOT trigger black-frame validation.
    video_intro_enabled: bool = True
    video_intro_seconds: float = 1.5

    # ------------------------------------------------------------------
    # Kokoro TTS Provider
    # ------------------------------------------------------------------

    # API key for a hosted Kokoro endpoint (leave empty to use local model).
    kokoro_api_key: str = Field(default="")

    # Voice ID — Kokoro American English voices: am_michael, am_adam, af_sarah, etc.
    kokoro_voice: str = "am_michael"

    # BCP-47 language code passed to Kokoro.
    kokoro_language: str = "en-US"

    # Speech speed multiplier (1.0 = natural).
    kokoro_speed: float = 1.0

    # Audio sample rate in Hz produced by Kokoro (native 24 kHz).
    kokoro_sample_rate: int = 24000

    # ------------------------------------------------------------------
    # WhisperX Forced Alignment
    # ------------------------------------------------------------------

    # Enable WhisperX forced alignment after TTS generation.
    # When True, alignment.json is written to audio/ alongside timing.json.
    # CaptionPipeline prefers alignment.json for subtitle timing when present.
    whisperx_enabled: bool = False

    # Reserved for future Whisper-based transcription support.
    # Forced alignment uses a fixed wav2vec2 phoneme model per language and
    # does not have configurable sizes — this setting is currently unused.
    whisperx_model: str = "base"

    # Device for WhisperX inference: "cpu" or "cuda".
    whisperx_device: str = "cpu"

    # ------------------------------------------------------------------
    # Subtitle Segmentation
    # ------------------------------------------------------------------

    # Segmentation mode: "semantic" (default, sentence/clause/pause aware)
    # or "legacy" (preserves previous purely-CPS-driven behaviour).
    subtitle_segmentation_mode: str = "semantic"

    # Target characters per second for subtitle segmentation.
    # Subtitles are split when CPS would exceed this value.
    # Lower than max_cps so there is headroom for natural variation.
    subtitle_target_cps: float = 15.0

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    request_timeout: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
