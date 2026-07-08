"""Provider validator — checks API keys and basic connectivity."""

from __future__ import annotations

import socket
from urllib.parse import urlparse


from .models import CheckResult, CheckStatus


def _is_reachable(host: str, port: int = 443, timeout: float = 5.0) -> bool:
    """Return True if host:port is reachable within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _host_from_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed.hostname or url


def validate_providers() -> list[CheckResult]:
    """Validate all configured providers. Non-fatal on connectivity failures."""
    results: list[CheckResult] = []

    try:
        from ytfactory.config.settings import Settings
        settings = Settings()
    except Exception as exc:
        results.append(CheckResult(
            name="providers:settings",
            status=CheckStatus.ERROR,
            message="Cannot load settings for provider validation",
            detail=str(exc),
        ))
        return results

    # LLM provider
    results.extend(_check_llm_provider(settings))

    # Search provider
    results.extend(_check_search_provider(settings))

    # Image provider
    results.extend(_check_image_provider(settings))

    # TTS provider
    results.extend(_check_tts_provider(settings))

    return results


def _check_llm_provider(settings: object) -> list[CheckResult]:
    results: list[CheckResult] = []
    provider = getattr(settings, "llm_provider", "gemini")

    if provider == "gemini":
        key = getattr(settings, "gemini_api_key", "")
        if not key:
            results.append(CheckResult(
                name="provider:gemini",
                status=CheckStatus.ERROR,
                message="GEMINI_API_KEY not set",
            ))
        else:
            reachable = _is_reachable("generativelanguage.googleapis.com")
            results.append(CheckResult(
                name="provider:gemini",
                status=CheckStatus.OK if reachable else CheckStatus.WARNING,
                message="Gemini: key present" + ("" if reachable else ", connectivity check failed"),
            ))

    elif provider == "anthropic":
        key = getattr(settings, "anthropic_api_key", "")
        base_url = getattr(settings, "anthropic_base_url", "https://api.anthropic.com")
        if not key:
            results.append(CheckResult(
                name="provider:anthropic",
                status=CheckStatus.ERROR,
                message="ANTHROPIC_API_KEY not set",
            ))
        else:
            host = _host_from_url(base_url)
            reachable = _is_reachable(host)
            results.append(CheckResult(
                name="provider:anthropic",
                status=CheckStatus.OK if reachable else CheckStatus.WARNING,
                message=f"Anthropic: key present, endpoint={host}" + ("" if reachable else " (unreachable)"),
            ))

    elif provider == "groq":
        key = getattr(settings, "groq_api_key", "")
        if not key:
            results.append(CheckResult(
                name="provider:groq",
                status=CheckStatus.ERROR,
                message="GROQ_API_KEY not set",
            ))
        else:
            reachable = _is_reachable("api.groq.com")
            results.append(CheckResult(
                name="provider:groq",
                status=CheckStatus.OK if reachable else CheckStatus.WARNING,
                message="Groq: key present" + ("" if reachable else ", connectivity check failed"),
            ))

    else:
        results.append(CheckResult(
            name=f"provider:{provider}",
            status=CheckStatus.WARNING,
            message=f"Unknown LLM provider '{provider}' — skipping validation",
        ))

    return results


def _check_search_provider(settings: object) -> list[CheckResult]:
    provider = getattr(settings, "search_provider", "tavily")
    if provider == "tavily":
        key = getattr(settings, "tavily_api_key", "")
        if not key:
            return [CheckResult(
                name="provider:tavily",
                status=CheckStatus.ERROR,
                message="TAVILY_API_KEY not set",
            )]
        reachable = _is_reachable("api.tavily.com")
        return [CheckResult(
            name="provider:tavily",
            status=CheckStatus.OK if reachable else CheckStatus.WARNING,
            message="Tavily: key present" + ("" if reachable else ", connectivity check failed"),
        )]
    return [CheckResult(
        name=f"provider:{provider}",
        status=CheckStatus.WARNING,
        message=f"Unknown search provider '{provider}'",
    )]


def _check_image_provider(settings: object) -> list[CheckResult]:
    provider = getattr(settings, "image_provider", "huggingface")
    if provider == "huggingface":
        token = getattr(settings, "hf_token", "")
        reachable = _is_reachable("huggingface.co")
        return [CheckResult(
            name="provider:huggingface",
            status=CheckStatus.OK if reachable else CheckStatus.WARNING,
            message="HuggingFace: " + ("token present" if token else "no token (public models OK)") + ("" if reachable else ", unreachable"),
        )]
    if provider == "gemini":
        key = getattr(settings, "gemini_api_key", "")
        return [CheckResult(
            name="provider:gemini-image",
            status=CheckStatus.OK if key else CheckStatus.ERROR,
            message="Gemini image: " + ("key present" if key else "GEMINI_API_KEY not set"),
        )]
    return [CheckResult(
        name=f"provider:{provider}-image",
        status=CheckStatus.WARNING,
        message=f"Unknown image provider '{provider}'",
    )]


def _check_tts_provider(settings: object) -> list[CheckResult]:
    provider = getattr(settings, "tts_provider", "edge")
    if provider == "edge":
        reachable = _is_reachable("speech.platform.bing.com")
        return [CheckResult(
            name="provider:edge-tts",
            status=CheckStatus.OK if reachable else CheckStatus.WARNING,
            message="Edge TTS: no key needed" + ("" if reachable else ", connectivity check failed"),
        )]
    if provider == "kokoro":
        try:
            import importlib.util
            spec = importlib.util.find_spec("kokoro")
            if spec is None:
                raise ImportError("kokoro not installed")
            return [CheckResult(
                name="provider:kokoro",
                status=CheckStatus.OK,
                message="Kokoro: package available (local model)",
            )]
        except ImportError:
            return [CheckResult(
                name="provider:kokoro",
                status=CheckStatus.WARNING,
                message="Kokoro package not installed — run: uv pip install kokoro soundfile",
            )]
    if provider == "elevenlabs":
        key = getattr(settings, "elevenlabs_api_key", "")
        return [CheckResult(
            name="provider:elevenlabs",
            status=CheckStatus.OK if key else CheckStatus.ERROR,
            message="ElevenLabs: " + ("key present" if key else "ELEVENLABS_API_KEY not set"),
        )]
    return [CheckResult(
        name=f"provider:{provider}-tts",
        status=CheckStatus.WARNING,
        message=f"Unknown TTS provider '{provider}'",
    )]
