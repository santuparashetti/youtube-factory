from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    gemini_api_key: str = Field(default="")
    tavily_api_key: str = Field(default="")

    llm_provider: str = "gemini"
    search_provider: str = "tavily"

    gemini_model: str = "gemini-2.5-flash"

    request_timeout: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )