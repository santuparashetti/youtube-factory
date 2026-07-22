from pydantic import Field, field_validator
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
    hf_vision_provider: str = "hf-inference"
    hf_vision_model: str = ""
    groq_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    anthropic_base_url: str = Field(default="")
    kokoro_api_key: str = Field(default="")

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    llm_provider: str = "anthropic"
    search_provider: str = "tavily"
    tts_provider: str = "kokoro"
    image_provider: str = "huggingface"

    # Provider-independent voice profile selector. All narration references the
    # profile instead of provider-specific configuration. See
    # video_core.providers.tts.voice_profiles.
    voice_profile: str = "atma_theory"

    # Maximum number of concurrent *vision review* requests. Throttles only the
    # vision QA gate so cloud providers don't hit per-user concurrency limits
    # (HTTP 429). Does NOT affect image generation, TTS, WhisperX, or rendering.
    # Validated to 1..100 at load time.
    vision_max_concurrency: int = 5

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
    # Hugging Face LLM (Inference Providers)
    # ------------------------------------------------------------------

    hf_llm_provider: str = "auto"
    hf_llm_model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    hf_llm_timeout: int = 60
    hf_llm_max_retries: int = 3

    # ------------------------------------------------------------------
    # DeepInfra LLM
    # ------------------------------------------------------------------

    deepinfra_api_key: str = Field(default="")
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"
    deepinfra_model: str = "meta-llama/Llama-3.3-70B-Instruct"
    deepinfra_timeout: int = 60
    deepinfra_max_retries: int = 3

    # ------------------------------------------------------------------
    # Kokoro TTS Provider
    # ------------------------------------------------------------------

    kokoro_voice: str = "am_michael"
    kokoro_speed: float = 0.85
    kokoro_sample_rate: int = 24000

    # ------------------------------------------------------------------
    # Cartesia TTS Provider (premium cloud narration)
    # ------------------------------------------------------------------

    cartesia_api_key: str = Field(default="")
    cartesia_model: str = "sonic-3.5"
    cartesia_voice_id: str = ""
    cartesia_speed: float = 0.88
    cartesia_output_format: str = "wav"
    cartesia_timeout: int = 90
    cartesia_max_chars: int = 2000
    cartesia_cache_enabled: bool = True
    cartesia_pronunciation_dict_id: str = Field(default="")
    cartesia_sample_rate: int = 48000
    cartesia_emotion: str = "contemplative"

    # ------------------------------------------------------------------
    # TTS Retry Control
    # ------------------------------------------------------------------

    # Accessed directly by KokoroProvider in video_core (kokoro.py:199).
    tts_auto_retry: bool = True
    tts_max_retries: int = 3

    # ------------------------------------------------------------------
    # TTS Analytics & Cost Tracking
    # ------------------------------------------------------------------

    tts_analytics_enabled: bool = True
    tts_cost_tracking_enabled: bool = True
    tts_log_per_scene: bool = True
    tts_summary_enabled: bool = True
    tts_verify_cache: bool = True

    # ------------------------------------------------------------------
    # Pipeline Quality Gates
    # ------------------------------------------------------------------

    stop_on_quality_gate_failure: bool = True

    # ------------------------------------------------------------------
    # TTS Provider Pricing (loaded from configuration)
    # ------------------------------------------------------------------

    cartesia_credits_per_character: float = 0.0
    cartesia_credits_per_request: float = 0.0
    cartesia_usd_per_credit: float = 0.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @field_validator("vision_max_concurrency")
    @classmethod
    def _validate_vision_max_concurrency(cls, v: int) -> int:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError(
                f"VISION_MAX_CONCURRENCY must be an integer, got {v!r}"
            )
        if v < 1 or v > 100:
            raise ValueError(
                f"VISION_MAX_CONCURRENCY must be between 1 and 100 (got {v})"
            )
        return v
