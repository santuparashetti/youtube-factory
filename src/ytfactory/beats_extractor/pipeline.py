"""BeatsExtractorPipeline — identifies protected narrative beats in a source script.

Runs before SourceRefinerPipeline. Extracts 6-10 core beats that MUST survive
all editing passes. Result is cached to beats.json and threaded through state
so every downstream step (refiner, composer A/B, recomposer, verifier) can
enforce the same beat list without hardcoding story-specific content.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()

_SYSTEM_PROMPT = """\
You are a story analyst for a spiritual documentary YouTube channel.

Read the source script below and identify 6-10 core narrative and
philosophical beats that MUST survive all editing passes.

A beat is either:
- A specific story moment (setup, turning point, consequence, resolution)
- A core philosophical teaching that the whole script depends on
- A specific metaphor mapping (X = Y) that carries the meaning

Rules:
- Be specific, not generic. "The traveler gets distracted" is too vague.
  "The traveler stops to count gold coins and cannot make the number settle
  at 999 or 1001" is a beat.
- Metaphor mappings are always beats. If the source says "X represents Y",
  that is a beat.
- The climax moment is always a beat.
- The final teaching/resolution is always a beat.
- Maximum 10 beats. Minimum 6.
- Each beat: one or two sentences max.

Return ONLY a JSON array. No preamble, no explanation, no markdown fences.

Format:
[
  { "id": 1, "beat": "description of beat" },
  { "id": 2, "beat": "description of beat" }
]"""


def format_beats_list(beats: list[dict]) -> str:
    """Format beats as a numbered plaintext list for prompt injection."""
    return "\n".join(f"{b['id']}. {b['beat']}" for b in beats)


class BeatsExtractorPipeline:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "source_refiner")

    def run(self, project_id: str, source_script: str) -> list[dict]:
        """Extract beats from source_script. Returns cached result if beats.json exists."""
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        beats_file = script_dir / "beats.json"

        if beats_file.exists():
            beats = json.loads(beats_file.read_text(encoding="utf-8"))
            logger.info("BeatsExtractor: loaded {} beats from cache (beats.json)", len(beats))
            for b in beats:
                logger.info("  Beat {}: {}", b["id"], b["beat"])
            return beats

        console.print(
            "\n[bold blue]⟡  Beats Extractor[/bold blue] — identifying protected beats..."
        )

        try:
            response = self._llm.generate(
                source_script,
                system_prompt=_SYSTEM_PROMPT,
                temperature=0.2,
            )
            raw = response.text.strip()
        except Exception as exc:
            logger.error("BeatsExtractor: LLM call failed — {}", exc)
            raise

        try:
            # Strip markdown fences if the model added them
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                raw = match.group(0)
            beats = json.loads(raw)
            if not isinstance(beats, list) or len(beats) < 1:
                raise ValueError("Expected non-empty JSON array")
            beats = [{"id": b["id"], "beat": str(b["beat"])} for b in beats]
        except Exception as exc:
            logger.error("BeatsExtractor: failed to parse beats JSON — {}\nRaw: {}", exc, raw[:500])
            raise RuntimeError(f"BeatsExtractor: invalid JSON response: {exc}") from exc

        beats_file.write_text(json.dumps(beats, indent=2), encoding="utf-8")

        logger.info("BeatsExtractor: extracted {} beats:", len(beats))
        for b in beats:
            logger.info("  Beat {}: {}", b["id"], b["beat"])

        beats_display = "\n".join(f"  {b['id']}. {b['beat']}" for b in beats)
        console.print(
            Panel(
                f"[green]Extracted[/green] {len(beats)} protected beats\n\n{beats_display}",
                title="Beats Extractor",
                border_style="blue",
            )
        )

        return beats
