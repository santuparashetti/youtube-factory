from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger

from video_core.providers.llm.base import LLMProvider
from ytfactory.beats_extractor.pipeline import format_beats_list
from ytfactory.composer.judge import JudgeVerdict
from ytfactory.composer.pipeline import _validate_rehook_present


_NARRATION_WPM = 130


def guided_recompose(
    script_a: str,
    script_b: str,
    verdict: JudgeVerdict,
    provider: LLMProvider,
    settings: object,
    beats: list[dict] | None = None,
    target_minutes: int = 5,
) -> Optional[str]:
    """Write a new whole-cloth script guided by the judge's section map.
    Returns the recomposed text, or None on failure.
    Caller is responsible for falling back to the judge winner.
    """
    if not getattr(settings, "GUIDED_RECOMPOSE_ENABLED", True):
        logger.info("Guided recomposer disabled — skipping.")
        return None

    raw_prompt = _load_prompt("GUIDED_RECOMPOSER_PROMPT.md")
    beats_text = format_beats_list(beats) if beats else "(No beats extracted for this script.)"
    center = target_minutes * _NARRATION_WPM
    prompt = raw_prompt.format(
        beats_list=beats_text,
        recompose_min=int(center * 0.90),
        recompose_max=int(center * 1.00),
        source_words_min=int(center * 1.05),
        source_words_max=int(center * 1.20),
    )

    section_lines = "\n".join(
        f"- {s.name}: Script {s.winner} is stronger ({s.reason})"
        for s in verdict.sections
    )
    user_content = (
        f"SECTION MAP (use as guidance, not as a cut list):\n{section_lines}\n\n"
        f"SCRIPT A:\n\n{script_a}\n\n"
        "---\n\n"
        f"SCRIPT B:\n\n{script_b}"
    )

    try:
        response = provider.generate(
            user_content,
            system_prompt=prompt,
            temperature=0.5,
            model=getattr(settings, "GUIDED_RECOMPOSER_MODEL", None),
            max_tokens=16000,
        )
        recomposed = response.text.strip()
    except Exception as e:
        logger.warning("Recomposer LLM call failed ({}: {}).", type(e).__name__, e)
        return None

    if not recomposed or not recomposed.strip():
        logger.warning("Recomposer returned empty content — falling back.")
        return None

    if not _validate_rehook_present(recomposed):
        logger.warning("Recomposed script failed rehook validation.")
        return None

    logger.info("Guided recomposition succeeded and passed rehook validation.")
    return recomposed


def _load_prompt(filename: str) -> str:
    prompt_dir = Path(__file__).parent.parent / "prompts"
    return (prompt_dir / filename).read_text(encoding="utf-8")
