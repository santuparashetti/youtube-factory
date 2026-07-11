"""LLMSubtitleEditor — subtitle editing provider backed by the configured LLM.

Wraps the existing LLMProvider interface.  Handles JSON serialisation,
prompt construction, response parsing, and markdown-fence stripping.
All cue_id validation and retry logic live in SubtitleEditingEngine.
"""

from __future__ import annotations

import json
import re

from loguru import logger

from video_core.providers.llm.base import LLMProvider

from ..prompt import EDITORIAL_SYSTEM_PROMPT
from ..provider import CueInput, CueOutput, EditResult, SubtitleEditorProvider


class LLMSubtitleEditor(SubtitleEditorProvider):
    """Subtitle editor that delegates generation to an LLMProvider."""

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    def edit_cues(
        self,
        inputs: list[CueInput],
        *,
        pass_number: int = 1,
        retry_error: str | None = None,
        previous_score: int = 0,
        previous_failed_axes: list[str] | None = None,
    ) -> EditResult:
        user_prompt = self._build_user_prompt(
            inputs,
            pass_number=pass_number,
            retry_error=retry_error,
            previous_score=previous_score,
            previous_failed_axes=previous_failed_axes or [],
        )

        response = self._llm.generate(
            user_prompt,
            system_prompt=EDITORIAL_SYSTEM_PROMPT,
            temperature=0.1,
        )

        logger.debug(
            "Subtitle editor LLM response: {} chars (tokens={})",
            len(response.text),
            response.total_tokens,
        )

        return self._parse_response(response.text, pass_number=pass_number)

    # ── Internal ───────────────────────────────────────────────────────────

    def _build_user_prompt(
        self,
        inputs: list[CueInput],
        *,
        pass_number: int,
        retry_error: str | None,
        previous_score: int,
        previous_failed_axes: list[str],
    ) -> str:
        cues_json = json.dumps(
            [
                {
                    "cue_id": inp.cue_id,
                    "start_time": inp.start_time,
                    "end_time": inp.end_time,
                    "duration_secs": inp.duration_secs,
                    "cps": inp.cps,
                    "original_text": inp.original_text,
                }
                for inp in inputs
            ],
            ensure_ascii=False,
            indent=2,
        )

        parts: list[str] = [f"Editorial pass {pass_number}/3."]

        if pass_number > 1:
            axes_str = (
                ", ".join(previous_failed_axes) if previous_failed_axes else "none"
            )
            parts.append(
                f"Previous quality score: {previous_score}/100. "
                f"Failed axes: {axes_str}. "
                f"Focus your improvements on those axes this pass."
            )

        if retry_error:
            parts += [
                "",
                f"VALIDATION ERROR from previous attempt: {retry_error}",
                "Correct this before returning — every input cue_id must appear exactly once.",
            ]

        parts += [
            "",
            f"Input cues ({len(inputs)} total):",
            "```json",
            cues_json,
            "```",
            "",
            "Return a single JSON object (no markdown fences) with this exact structure:",
            "",
            json.dumps(
                {
                    "edited_cues": [
                        {
                            "cue_id": "<int>",
                            "text": "<edited — use \\n for a two-line break>",
                        }
                    ],
                    "quality_score": "<0-100 integer>",
                    "failed_axes": ["<axis name>"],
                    "notes": "<editorial decisions, unavoidable breaks, CPS >20 flags>",
                },
                indent=2,
            ),
            "",
            "Rules:",
            "- Return exactly one entry per input cue, in the same order, with the same cue_id.",
            "- Only text may change. Timing and cue count are frozen.",
            "- Use \\n within text to indicate a two-line display break.",
            "- quality_score: self-evaluate all 6 quality axes. Score 0–100.",
            "- failed_axes: list axes below target (empty list if score >= 95).",
        ]

        return "\n".join(parts)

    @staticmethod
    def _parse_response(text: str, pass_number: int) -> EditResult:
        text = text.strip()

        # Strip markdown fences if present
        text = re.sub(r"^```[^\n]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
        text = text.strip()

        data = json.loads(text)

        outputs = [
            CueOutput(cue_id=int(c["cue_id"]), text=str(c["text"]))
            for c in data["edited_cues"]
        ]

        return EditResult(
            outputs=outputs,
            quality_score=int(data.get("quality_score", 0)),
            failed_axes=list(data.get("failed_axes", [])),
            notes=str(data.get("notes", "")),
            pass_number=pass_number,
        )
