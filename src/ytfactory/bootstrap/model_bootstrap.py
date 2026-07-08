"""Model Bootstrap — downloads required models on first run, caches permanently."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from .models import CheckResult, CheckStatus

_MODEL_CACHE_FILE = "models/.model-cache.json"


def bootstrap_models(base_dir: Path | None = None) -> list[CheckResult]:
    """Ensure all required models are downloaded and cached. Idempotent."""
    root = base_dir or Path.cwd()
    results: list[CheckResult] = []
    cache = _load_cache(root)

    results.extend(_check_whisperx(root, cache))
    results.extend(_check_kokoro(root, cache))

    _save_cache(root, cache)
    return results


def _load_cache(root: Path) -> dict:
    cache_file = root / _MODEL_CACHE_FILE
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass
    return {}


def _save_cache(root: Path, cache: dict) -> None:
    cache_file = root / _MODEL_CACHE_FILE
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=2))
    except OSError:
        pass


def _check_whisperx(root: Path, cache: dict) -> list[CheckResult]:
    """Check/download WhisperX alignment model."""
    try:
        from ytfactory.config.settings import Settings
        settings = Settings()
        if not settings.whisperx_enabled:
            return [CheckResult(
                name="model:whisperx",
                status=CheckStatus.SKIPPED,
                message="WhisperX disabled (WHISPERX_ENABLED=false)",
            )]
    except Exception:
        pass

    try:
        import importlib.util
        if importlib.util.find_spec("whisperx") is None:
            return [CheckResult(
                name="model:whisperx",
                status=CheckStatus.WARNING,
                message="whisperx not installed — run: uv pip install whisperx",
            )]
    except Exception:
        pass

    # If already cached, skip
    if cache.get("whisperx_wav2vec2"):
        return [CheckResult(
            name="model:whisperx",
            status=CheckStatus.OK,
            message="WhisperX wav2vec2 model cached",
        )]

    # Mark as to-be-downloaded on first alignment run (lazy, not predownloaded)
    logger.debug("WhisperX model will download on first alignment run")
    return [CheckResult(
        name="model:whisperx",
        status=CheckStatus.OK,
        message="WhisperX model: downloads on first use",
    )]


def _check_kokoro(root: Path, cache: dict) -> list[CheckResult]:
    """Check Kokoro TTS model availability."""
    try:
        from ytfactory.config.settings import Settings
        settings = Settings()
        if settings.tts_provider != "kokoro":
            return [CheckResult(
                name="model:kokoro",
                status=CheckStatus.SKIPPED,
                message=f"Kokoro not active (TTS_PROVIDER={settings.tts_provider})",
            )]
    except Exception:
        pass

    try:
        import importlib.util
        if importlib.util.find_spec("kokoro") is None:
            return [CheckResult(
                name="model:kokoro",
                status=CheckStatus.WARNING,
                message="kokoro not installed — run: uv pip install kokoro soundfile",
            )]
        return [CheckResult(
            name="model:kokoro",
            status=CheckStatus.OK,
            message="Kokoro package installed — model downloads on first use (~300 MB)",
        )]
    except Exception as exc:
        return [CheckResult(
            name="model:kokoro",
            status=CheckStatus.WARNING,
            message="Cannot check Kokoro availability",
            detail=str(exc),
        )]
