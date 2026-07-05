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

    # Maximum characters per subtitle line (SRT convention: 42)
    subtitle_max_chars_per_line: int = 42

    # Maximum number of display lines per subtitle cue
    subtitle_max_lines: int = 2

    # Output format: "srt" (default); "webvtt" and "ass" reserved for future
    subtitle_format: str = "srt"

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
    # Runtime
    # ------------------------------------------------------------------

    request_timeout: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
