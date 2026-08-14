"""AtmaRefinerPipeline — 7-Beat script refinement for the Atma Theory channel.

Operates as an editor, not a replacement writer. The refinement:
  1. Receives the base/raw script and its pre-extracted ScriptIdentity.
  2. Makes ONE editing pass to align the script with the 7-Beat framework.
  3. Writes outputs to workspace/jobs/<id>/script/:
       - atma-refined.md         — the refined script text
       - atma-refinement-report.json — word count, validation summary

For targeted refinement after a human rejection, the pipeline receives the
current refined script + structured reviewer feedback, then edits ONLY the
flagged sections, preserving all unaffected content.

Idempotency: if atma-refined.md already exists AND no targeted feedback
is provided, the pipeline returns the cached output without an LLM call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from video_core.providers.llm.factory import get_llm_for_role
from ytfactory.atma_refiner.prompts import (
    build_7beat_system_prompt,
    build_initial_refinement_prompt,
    build_targeted_refinement_prompt,
)
from ytfactory.atma_refiner.validator import ScriptValidator
from ytfactory.config.settings import Settings
from ytfactory.domain.script_revision import ScriptIdentity, ScriptValidationResult
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()

_NARRATION_WPM = 130
_SYSTEM_PROMPT = build_7beat_system_prompt()


class AtmaRefinerPipeline:
    """Edit a script to satisfy the 7-Beat Atma Theory narrative framework.

    The LLM is used exclusively as an editor — one call, surgical edits,
    ScriptIdentity as a hard constraint.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_role(settings, "script")
        self._validator = ScriptValidator()

    def run(
        self,
        project_id: str,
        base_script: str,
        identity: ScriptIdentity,
        *,
        beats: list[dict] | None = None,
        reviewer_feedback: str | None = None,
        current_refined: str | None = None,
        target_minutes: int = 5,
        force: bool = False,
    ) -> tuple[str, ScriptValidationResult]:
        """Refine the script using the 7-Beat framework.

        Returns (refined_script_text, validation_result).

        Args:
            project_id: Workspace project identifier.
            base_script: The raw/imported base script text.
            identity: ScriptIdentity extracted before this call.
            beats: Protected narrative beats from BeatsExtractorPipeline.
            reviewer_feedback: Structured feedback from a human rejection.
                When present, runs targeted refinement of the current_refined
                script rather than an initial pass on base_script.
            current_refined: The current refined script (used with reviewer_feedback).
            target_minutes: Target narration duration in minutes.
            force: Bypass idempotency check and always re-run.
        """
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        refined_file = script_dir / "atma-refined.md"

        # Idempotency: use cached output for initial refinement only
        is_targeted = bool(reviewer_feedback and current_refined)
        if not force and not is_targeted and refined_file.exists():
            cached = refined_file.read_text(encoding="utf-8")
            if cached.strip():
                console.print(
                    f"\n[dim]Atma Refiner: cached atma-refined.md exists — "
                    f"delete it to re-run (project: {project_id})[/dim]"
                )
                validation = self._validator.validate(cached, identity, base_script)
                return cached, validation

        if is_targeted:
            label = "Targeted refinement (addressing reviewer feedback)"
            prompt = build_targeted_refinement_prompt(
                current_refined_script=current_refined,  # type: ignore[arg-type]
                base_script=base_script,
                identity=identity,
                reviewer_feedback=reviewer_feedback,  # type: ignore[arg-type]
                beats=beats,
            )
        else:
            label = "Initial 7-Beat refinement"
            source_wc = len(
                re.sub(r"\[[^\]]*\]", "", base_script).split()
            ) if base_script else 0
            prompt = build_initial_refinement_prompt(
                script_text=base_script,
                identity=identity,
                beats=beats,
                target_minutes=target_minutes,
                source_word_count=source_wc,
            )

        console.print(f"\n[bold magenta]✍  Atma Refiner[/bold magenta] — {label}...")

        response = self._llm.generate(
            prompt,
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.45,
        )
        refined = response.text.strip()

        if not refined:
            logger.error(
                "AtmaRefinerPipeline: LLM returned empty output — using base script"
            )
            refined = base_script

        words = len(refined.split())
        estimated_min = words / _NARRATION_WPM
        console.print(f"  [dim]Refined:[/dim] {words} words (~{estimated_min:.1f} min)")

        # Validate before returning to human review
        validation = self._validator.validate(refined, identity, base_script)

        # Write outputs
        refined_file.write_text(refined, encoding="utf-8")
        report_path = script_dir / "atma-refinement-report.json"
        report_path.write_text(
            json.dumps(
                {
                    "mode": "targeted" if is_targeted else "initial",
                    "target_minutes": target_minutes,
                    "word_count": words,
                    "estimated_minutes": round(estimated_min, 2),
                    "validation": validation.to_dict(),
                    "reviewer_feedback": reviewer_feedback,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        # Write engagement elements metadata for downstream scene planning.
        # JOURNEY_INVITATION is marked is_dedicated_scene=True; BRANDING_END
        # is marked is_final_scene=True. Scene planners can read this to apply
        # the correct scene_type (journey_invitation / brand_card) to each scene.
        engagement_path = script_dir / "engagement-elements.json"
        engagement_path.write_text(
            json.dumps(
                {
                    "elements": [e.to_dict() for e in validation.engagement_elements],
                    "scene_planning_hints": {
                        "journey_invitation": {
                            "scene_role": "journey_invitation",
                            "note": "Identify by [ENGAGEMENT: journey_invitation] marker or content.",
                        },
                        "branding_end": {
                            "scene_role": "brand_card",
                            "note": "Final scene — already handled by scene planner brand_card logic.",
                        },
                    },
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        status_color = "green" if validation.status == "PASS" else "yellow"
        console.print(
            Panel(
                f"[{status_color}]Refinement complete[/{status_color}] — "
                f"{words} words (~{estimated_min:.1f} min)\n"
                f"Validation: {validation.status} "
                f"({len(validation.flags)} flag(s))\n"
                f"[dim]→ atma-refined.md | atma-refinement-report.json[/dim]",
                title="Atma Refiner",
                border_style="magenta",
            )
        )

        return refined, validation
