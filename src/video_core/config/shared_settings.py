from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SharedSettings(BaseSettings):
    """Shared configuration — API keys, provider selectors, model names.

    Any factory built on video_core can extend this class. Only fields
    actively consumed by video_core providers live here; factory-specific
    thresholds, BGM, CTA, subtitle styling, etc. belong in the factory's
    own Settings subclass.
    """

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------

    gemini_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")
    hf_token: str = Field(default="")
    groq_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    anthropic_base_url: str = Field(default="https://litellm.smarthubai.net")
    kokoro_api_key: str = Field(default="")

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    llm_provider: str = "anthropic"
    search_provider: str = "tavily"
    tts_provider: str = "kokoro"
    image_provider: str = "huggingface"

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    gemini_text_model: str = "gemini-2.5-flash"
    gemini_image_model: str = "gemini-3.1-flash-lite-image"

    hf_image_model: str = "black-forest-labs/FLUX.1-schnell"
    hf_inference_provider: str = "auto"  # "auto" | "together" | "fal-ai" | "nebius" | "hf-inference"

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
    # Kokoro TTS Provider
    # ------------------------------------------------------------------

    kokoro_voice: str = "am_michael"
    kokoro_speed: float = 0.85
    kokoro_sample_rate: int = 24000

    # ------------------------------------------------------------------
    # TTS Retry Control
    # ------------------------------------------------------------------

    # Accessed directly by KokoroProvider in video_core (kokoro.py:199).
    tts_auto_retry: bool = True
    tts_max_retries: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
