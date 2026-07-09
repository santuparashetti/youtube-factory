"""Configuration validator — checks .env and Settings."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from .models import CheckResult, CheckStatus

# Keys required per LLM provider
_PROVIDER_KEYS: dict[str, list[str]] = {
    "gemini": ["GEMINI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "huggingface": ["HF_TOKEN"],
}


def _load_dotenv_values(env_file: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Values are stripped of quotes."""
    values: dict[str, str] = {}
    try:
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            values[key] = val
    except OSError:
        pass
    return values


def validate_config(base_dir: Path | None = None) -> list[CheckResult]:
    """Validate .env file and provider key presence. Idempotent.

    Reads the env file from *base_dir*/.env directly (not from CWD Settings)
    so that tests using temp directories work correctly.
    """
    root = base_dir or Path.cwd()
    results: list[CheckResult] = []

    # Check .env file presence
    env_file = root / ".env"
    if not env_file.exists():
        example = root / ".env.example"
        detail = (
            "Copy .env.example to .env and fill in API keys."
            if example.exists()
            else "Create .env from .env.example."
        )
        results.append(
            CheckResult(
                name="config:.env",
                status=CheckStatus.ERROR,
                message=".env file not found",
                detail=detail,
            )
        )
        return results

    results.append(
        CheckResult(
            name="config:.env",
            status=CheckStatus.OK,
            message=".env file present",
        )
    )

    # Parse env values directly so we read from base_dir, not CWD
    env_vals = _load_dotenv_values(env_file)

    # Attempt Settings load (uses CWD .env — best-effort, non-fatal)
    try:
        from ytfactory.config.settings import Settings

        Settings()  # Validates pydantic parsing; value not needed here
        results.append(
            CheckResult(
                name="config:settings",
                status=CheckStatus.OK,
                message="Settings loaded",
            )
        )
    except Exception as exc:
        results.append(
            CheckResult(
                name="config:settings",
                status=CheckStatus.WARNING,
                message="Settings load failed (non-fatal in tests)",
                detail=str(exc),
            )
        )

    # Check LLM provider key from parsed env file
    llm_provider = env_vals.get("LLM_PROVIDER", "gemini").lower()
    if llm_provider in _PROVIDER_KEYS:
        for key_name in _PROVIDER_KEYS[llm_provider]:
            val = env_vals.get(key_name, "")
            if not val:
                results.append(
                    CheckResult(
                        name=f"config:{key_name}",
                        status=CheckStatus.ERROR,
                        message=f"{key_name} not set (required for LLM_PROVIDER={llm_provider})",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        name=f"config:{key_name}",
                        status=CheckStatus.OK,
                        message=f"{key_name} present",
                    )
                )

    # Search provider
    search_provider = env_vals.get("SEARCH_PROVIDER", "tavily")
    if search_provider == "tavily":
        tavily_key = env_vals.get("TAVILY_API_KEY", "")
        if not tavily_key:
            results.append(
                CheckResult(
                    name="config:TAVILY_API_KEY",
                    status=CheckStatus.ERROR,
                    message="TAVILY_API_KEY not set (required for SEARCH_PROVIDER=tavily)",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="config:TAVILY_API_KEY",
                    status=CheckStatus.OK,
                    message="TAVILY_API_KEY present",
                )
            )

    # Image provider
    image_provider = env_vals.get("IMAGE_PROVIDER", "huggingface")
    if image_provider == "huggingface":
        hf_token = env_vals.get("HF_TOKEN", "")
        if not hf_token:
            results.append(
                CheckResult(
                    name="config:HF_TOKEN",
                    status=CheckStatus.WARNING,
                    message="HF_TOKEN not set (some HuggingFace models require it)",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="config:HF_TOKEN",
                    status=CheckStatus.OK,
                    message="HF_TOKEN present",
                )
            )

    # Provider summary
    tts_provider = env_vals.get("TTS_PROVIDER", "edge")
    results.append(
        CheckResult(
            name="config:providers",
            status=CheckStatus.OK,
            message=f"Providers: LLM={llm_provider}, search={search_provider}, image={image_provider}, tts={tts_provider}",
        )
    )

    return results


def migrate_config(base_dir: Path | None = None) -> list[str]:
    """Detect and migrate outdated configuration. Returns list of actions taken."""
    # Currently a no-op — reserved for future config version migrations.
    logger.debug("Config migration check: no migrations needed")
    return []
