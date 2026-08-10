from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field

from video_core.providers.llm.base import LLMProvider


class SectionVerdict(BaseModel):
    name: str
    winner: Literal["A", "B"]
    evidence: str
    reason: str


class JudgeVerdict(BaseModel):
    script_a_score: float = Field(ge=1.0, le=10.0)
    script_b_score: float = Field(ge=1.0, le=10.0)
    winner: Literal["A", "B"]
    hybrid_recommended: bool
    sections: list[SectionVerdict]
    hybrid_rationale: str
    verdict_summary: str


def judge_scripts(
    script_a: str,
    script_b: str,
    provider: LLMProvider,
    settings: object,
) -> Optional[JudgeVerdict]:
    """Call the judge model and return a JudgeVerdict.
    Returns None on any failure — caller falls back to Script A.
    """
    if not getattr(settings, "SCRIPT_JUDGE_ENABLED", True):
        logger.info("Script judge disabled — skipping.")
        return None

    prompt = _load_prompt("SCRIPT_JUDGE_PROMPT.md")
    user_content = (
        f"SCRIPT A:\n\n{script_a}\n\n"
        "---\n\n"
        f"SCRIPT B:\n\n{script_b}"
    )

    try:
        response = provider.generate(
            user_content,
            system_prompt=prompt,
            temperature=0,
            model=getattr(settings, "SCRIPT_JUDGE_MODEL", None),
        )
        data = json.loads(response.text.strip())
        verdict = JudgeVerdict(**data)

        # Hard rule: hybrid is always true when B wins at least one section —
        # the recomposer exists to cherry-pick those wins regardless of margin.
        b_wins = any(s.winner == "B" for s in verdict.sections)
        if b_wins and not verdict.hybrid_recommended:
            logger.info(
                "Judge set hybrid=False but B wins {} section(s) — overriding to True",
                sum(1 for s in verdict.sections if s.winner == "B"),
            )
            verdict = verdict.model_copy(update={"hybrid_recommended": True})

        logger.info(
            "Judge verdict: A={} B={} winner={} hybrid={}",
            verdict.script_a_score,
            verdict.script_b_score,
            verdict.winner,
            verdict.hybrid_recommended,
        )
        return verdict
    except Exception as e:
        logger.warning("Script judge failed ({}: {}) — will use Script A.", type(e).__name__, e)
        return None


def _load_prompt(filename: str) -> str:
    prompt_dir = Path(__file__).parent.parent / "prompts"
    return (prompt_dir / filename).read_text(encoding="utf-8")
