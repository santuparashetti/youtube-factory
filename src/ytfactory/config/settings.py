from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    # ------------------------------------------------------------------
    # API Keys
    # ------------------------------------------------------------------

    gemini_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")

    # ------------------------------------------------------------------
    # Providers
    # ------------------------------------------------------------------

    llm_provider: str = "gemini"
    search_provider: str = "tavily"

    # Supported:
    # - gemini_image
    # - comfyui
    # - automatic1111
    image_provider: str = "gemini_image"

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------

    gemini_model: str = "gemini-2.5-flash"

    # ------------------------------------------------------------------
    # Image Generation
    # ------------------------------------------------------------------

    image_width: int = 1280
    image_height: int = 720

    # ComfyUI Server
    comfyui_url: str = "http://127.0.0.1:8188"

    # Automatic1111 Server
    automatic1111_url: str = "http://127.0.0.1:7860"

    # ------------------------------------------------------------------
    # Runtime
    # ------------------------------------------------------------------

    request_timeout: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )