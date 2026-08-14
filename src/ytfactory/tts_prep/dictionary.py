"""Pronunciation dictionary loader.

Reads config/pronunciations.yaml from the project root (CWD).
Results are cached after the first load; call reset_cache() in tests.

YAML format (config/pronunciations.yaml):

    pronunciations:
      Dirghakala:
        pronunciation: "DEER-gha KAA-la"
        language: "Sanskrit"
      Patanjali:
        pronunciation: "pah-TAN-jah-lee"
        language: "Sanskrit"

A missing or malformed config is a non-fatal warning — the pipeline
continues with an empty dictionary (no pronunciation hints, no crash).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from loguru import logger

from .models import PronunciationHint

_CONFIG_PATH = "config/pronunciations.yaml"


@lru_cache(maxsize=4)
def _load_raw(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        logger.debug(
            "TTS PREP: pronunciations config not found at {} — empty dictionary",
            path,
        )
        return {}
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = data.get("pronunciations", {})
        logger.debug("TTS PREP: loaded {} pronunciation entries from {}", len(entries), path)
        return entries
    except Exception as exc:
        logger.warning("TTS PREP: failed to load pronunciations config — {}", exc)
        return {}


def get_dictionary(
    config_path: str | Path | None = None,
) -> dict[str, PronunciationHint]:
    """Return pronunciation dictionary as {canonical_term: PronunciationHint}.

    Lookups are case-sensitive to preserve canonical spelling.
    An empty dict is returned when the config file is absent.
    """
    raw = _load_raw(str(config_path or _CONFIG_PATH))
    result: dict[str, PronunciationHint] = {}
    for term, entry in raw.items():
        if not isinstance(entry, dict) or "pronunciation" not in entry:
            logger.warning(
                "TTS PREP: skipping malformed dictionary entry for {!r}", term
            )
            continue
        result[term] = PronunciationHint(
            term=str(term),
            pronunciation=str(entry["pronunciation"]),
            language=str(entry.get("language", "")),
            source="dictionary",
            confidence=1.0,
        )
    return result


def reset_cache() -> None:
    """Clear the dictionary cache — for testing only."""
    _load_raw.cache_clear()
