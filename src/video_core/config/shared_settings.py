from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ImageModelTier(BaseModel):
    id: str = ""
    provider: str = "auto"


class ImageModelRegistry(BaseModel):
    tier1: ImageModelTier = ImageModelTier(id="black-forest-labs/FLUX.1-schnell", provider="auto")
    tier2: ImageModelTier = ImageModelTier(id="Qwen/Qwen-Image", provider="auto")
    tier3: ImageModelTier = ImageModelTier(id="black-forest-labs/FLUX.1-dev", provider="auto")

    def for_tier(self, tier: int) -> ImageModelTier:
        return {1: self.tier1, 2: self.tier2, 3: self.tier3}[tier]


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

    # OpenRouter provider routing — pin requests to a specific upstream
    # provider so model routing is deterministic (no silent fallbacks).
    # Empty string = let OpenRouter decide (default behavior).
    openrouter_provider: str = ""
    openrouter_allow_fallbacks: bool = True

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
    vision_max_concurrency: int = 1

    # ------------------------------------------------------------------
    # Per-Role LLM Models (provider-agnostic)
    # ------------------------------------------------------------------
    # Provider-agnostic default model — used by all pipeline stages unless
    # overridden by a per-role field below.  Replaces the old pattern of
    # using ANTHROPIC_MODEL as the implicit default for everything.
    # Resolution: per-role field > LLM_DEFAULT_MODEL > provider-specific
    # model (ANTHROPIC_MODEL, GEMINI_TEXT_MODEL, etc.).
    llm_default_model: str = ""

    # Each pipeline stage can use a different model by setting the
    # corresponding env var (e.g. SCRIPT_MODEL=openai/gpt-5.6-luna-pro).
    # Empty string = fall back to LLM_DEFAULT_MODEL, then provider default.
    # These are resolved by get_llm_for_role() in the factory.
    script_model: str = ""
    scene_planner_model: str = ""
    research_model: str = ""
    title_model: str = ""
    subtitle_model: str = ""

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    gemini_text_model: str = "gemini-2.5-flash"
    gemini_image_model: str = "gemini-3.1-flash-lite-image"

    hf_image_model: str = "black-forest-labs/FLUX.1-schnell"
    hf_inference_provider: str = "auto"

    image_model_tier1_id: str = "black-forest-labs/FLUX.1-schnell"
    image_model_tier1_provider: str = "auto"
    image_model_tier2_id: str = "Qwen/Qwen-Image"
    image_model_tier2_provider: str = "auto"
    image_model_tier3_id: str = "black-forest-labs/FLUX.1-dev"
    image_model_tier3_provider: str = "auto"

    @model_validator(mode="after")
    def _warn_deprecated_image_model_env(self) -> "SharedSettings":
        import logging
        import os

        logger = logging.getLogger(__name__)
        deprecated = []
        if os.getenv("HF_IMAGE_MODEL"):
            deprecated.append("HF_IMAGE_MODEL")
        if os.getenv("HF_INFERENCE_PROVIDER"):
            deprecated.append("HF_INFERENCE_PROVIDER")
        if deprecated:
            logger.warning(
                "{} is deprecated, use IMAGE_MODEL_TIER{{1,2,3}}_ID and IMAGE_MODEL_TIER{{1,2,3}}_PROVIDER instead.",
                " and ".join(deprecated),
            )
        return self

    @property
    def image_model_registry(self) -> ImageModelRegistry:
        return ImageModelRegistry(
            tier1=ImageModelTier(id=self.image_model_tier1_id, provider=self.image_model_tier1_provider),
            tier2=ImageModelTier(id=self.image_model_tier2_id, provider=self.image_model_tier2_provider),
            tier3=ImageModelTier(id=self.image_model_tier3_id, provider=self.image_model_tier3_provider),
        )

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
    # Fish Audio TTS Provider
    # ------------------------------------------------------------------

    fish_api_key: str = Field(default="")
    fish_model: str = "s2.1-pro-free"
    fish_reference_id: str = ""
    fish_format: str = "mp3"
    fish_timeout: int = 60
    fish_max_retries: int = 3
    fish_max_chars: int = 2000
    fish_cache_enabled: bool = True
    fish_speed: float = 1.0
    fish_sample_rate: int = 44100
    fish_temperature: float = 0.7
    fish_top_p: float = 0.7
    fish_repetition_penalty: float = 1.2
    fish_max_new_tokens: int = 1024
    fish_normalize: bool = True

    # ------------------------------------------------------------------
    # ElevenLabs TTS Provider
    # ------------------------------------------------------------------

    elevenlabs_api_key: str = Field(default="")
    elevenlabs_model: str = "eleven_flash_v2_5"
    elevenlabs_voice_id: str = ""
    elevenlabs_output_format: str = "mp3_44100_128"
    elevenlabs_timeout: int = 60
    elevenlabs_max_chars: int = 2000
    elevenlabs_cache_enabled: bool = True
    elevenlabs_sample_rate: int = 44100

    # ------------------------------------------------------------------
    # TTS Retry Control
    # ------------------------------------------------------------------

    # Accessed directly by KokoroProvider in video_core (kokoro.py:199).
    tts_auto_retry: bool = True
    tts_max_retries: int = 3

    # Voice enable/disable — when False, no TTS provider is called and silent
    # audio is generated instead so the renderer still has narration tracks.
    voice_enabled: bool = True

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

    # ------------------------------------------------------------------
    # Scene Planner — Entity Grounding
    # ------------------------------------------------------------------

    # Model used for the entity extraction pass (cheap/fast model).
    # Defaults to a fast model; override via env ENTITY_EXTRACTION_MODEL.
    entity_extraction_model: str = ""

    # Model used for the faithfulness validation pass (cheap/fast model).
    # Defaults to a fast model; override via env FAITHFULNESS_VALIDATION_MODEL.
    faithfulness_validation_model: str = ""

    # Master switch for faithfulness validation gate.
    faithfulness_validation_enabled: bool = True

    # ------------------------------------------------------------------
    # Audience Profile
    # ------------------------------------------------------------------

    # Governs character/scene defaults in all visual prompts.
    # "western_english" = US/UK/AU/CA audience; Western characters + symbolic defaults.
    # Future: "india_english" for India-targeted English content, "kannada" for Kannada variant.
    AUDIENCE_PROFILE: str = "western_english"

    # Anchor character — pipeline-internal identifier.
    # ANCHOR_CHARACTER_ID is used in system prompts and internal artifacts ONLY.
    # It must NEVER appear in viewer-facing output. KaiFirewallViolation enforces this.
    ANCHOR_CHARACTER_ENABLED: bool = True
    ANCHOR_CHARACTER_ID: str = "Kai"

    # Scene Planner V2
    VISUAL_BIBLE_ENABLED: bool = True
    HYBRID_STYLE_ENABLED: bool = True
    KAI_POSE_DISCIPLINE_ENABLED: bool = True

    # Script Judge + Guided Recomposer
    SCRIPT_JUDGE_ENABLED: bool = True
    SCRIPT_JUDGE_MODEL: str = "deepseek/deepseek-v3.2"
    GUIDED_RECOMPOSE_ENABLED: bool = True
    GUIDED_RECOMPOSER_MODEL: str = "deepseek/deepseek-v3.2"

    # Visual Anchor generation — primary + fallback model
    VISUAL_ANCHOR_MODEL: str = "google/gemini-2.5-flash-lite"
    VISUAL_ANCHOR_FALLBACK_MODEL: str = "deepseek/deepseek-v4-pro"

    # Faithfulness validator — primary + fallback model
    FAITHFULNESS_VALIDATOR_FALLBACK_MODEL: str = "deepseek/deepseek-v4-flash"

    # ------------------------------------------------------------------
    # Post-processing: Video Split
    # ------------------------------------------------------------------

    # Split final.mp4 into 2-3 parts at scene boundaries after rendering
    # completes. Output goes to Epidemic Sound for BGM/sound layering.
    video_split_enabled: bool = Field(default=False, alias="VIDEO_SPLIT_ENABLED")
    video_split_length_minutes: float = Field(default=4.0, alias="VIDEO_SPLIT_LENGTH")

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
