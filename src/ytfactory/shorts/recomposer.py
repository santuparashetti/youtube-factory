"""S2b — Targeted Short Script Recomposer.

Accepts a failing ShortsScript and a structured QA report.
Makes minimum necessary edits: preserves strong sections, rewrites only broken ones.
Python reassembles full_script and recalculates metrics — the LLM never generates
full_script directly.
"""

from __future__ import annotations

import json
import re

from loguru import logger

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.config.settings import Settings
from ytfactory.shorts.models import ShortsScript, ShortsScriptQAReport
from ytfactory.shorts.prompts.recomposer import (
    RECOMPOSER_SYSTEM_PROMPT,
    build_recompose_prompt,
)

_SECTIONS = ("hook", "setup", "story", "revelation", "open_loop")


class ShortScriptRecomposer:
    def __init__(self, settings: Settings) -> None:
        self._llm = get_llm_for_role(settings, "script")
        self._settings = settings

    def recompose(
        self,
        script: ShortsScript,
        qa_report: ShortsScriptQAReport,
        sibling_scripts: list[ShortsScript],
        parent_script_md: str,
    ) -> ShortsScript:
        """Return a recomposed ShortsScript with targeted edits.

        Preserves sections listed in qa_report.preserve_sections verbatim.
        Rewrites sections listed in qa_report.rewrite_sections.
        Reassembles full_script and recalculates word_count / duration in Python.
        """
        preserve = set(qa_report.preserve_sections)
        rewrite = set(qa_report.rewrite_sections)

        if not rewrite:
            logger.warning(
                "Recomposer: no sections marked for rewrite in QA report for {}. "
                "Returning original script unchanged.",
                script.short_id,
            )
            return script

        logger.info(
            "Recomposer: recomposing {} — preserve={}, rewrite={}",
            script.short_id,
            sorted(preserve),
            sorted(rewrite),
        )

        prompt = build_recompose_prompt(
            script, qa_report, sibling_scripts, parent_script_md
        )
        response = self._llm.generate(
            prompt,
            system_prompt=RECOMPOSER_SYSTEM_PROMPT,
            temperature=0.4,
            json_mode=True,
        )

        text = _strip_fences(response.text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Recomposer: LLM returned invalid JSON for {script.short_id}. "
                f"Preview: {text[:300]}"
            ) from exc

        # Merge: preserve originals, take LLM rewrites
        new_sections: dict[str, str] = {}
        for section in _SECTIONS:
            original = getattr(script, section, "").strip()
            llm_value = data.get(section, "").strip()

            if section in preserve:
                # Must use original verbatim
                new_sections[section] = original
            elif section in rewrite:
                # Use LLM rewrite, fallback to original if LLM returned empty
                new_sections[section] = llm_value if llm_value else original
            else:
                # Unspecified — use original (safest choice)
                new_sections[section] = original

        # Python assembles full_script — never from LLM
        full_script = "\n\n".join([
            new_sections["hook"],
            new_sections["setup"],
            new_sections["story"],
            new_sections["revelation"],
            new_sections["open_loop"],
        ])
        word_count = len(full_script.split())
        duration = (word_count / self._settings.shorts_narration_wpm) * 60

        logger.info(
            "Recomposer: {} recomposed — {} words, {:.1f}s",
            script.short_id, word_count, duration,
        )

        return script.model_copy(update={
            "hook": new_sections["hook"],
            "setup": new_sections["setup"],
            "story": new_sections["story"],
            "revelation": new_sections["revelation"],
            "open_loop": new_sections["open_loop"],
            "full_script": full_script,
            "estimated_word_count": word_count,
            "target_duration_seconds": duration,
            "validation_passed": False,  # re-validated by caller
            "scores": None,
        })


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()
