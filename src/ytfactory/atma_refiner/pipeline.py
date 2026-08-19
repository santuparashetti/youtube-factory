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

from video_core.providers.llm.factory import get_llm_for_role, get_llm_for_task
from video_core.providers.llm.tasks import LLMTask
from ytfactory.atma_refiner.judge import ScriptJudge
from ytfactory.atma_refiner.prompts import (
    build_7beat_system_prompt,
    build_format_pass_prompt,
    build_initial_refinement_prompt,
    build_targeted_refinement_prompt,
)
from ytfactory.atma_refiner.refinement_loop import RefinementLoop
from ytfactory.atma_refiner.validator import ScriptValidator
from ytfactory.config.settings import Settings
from ytfactory.domain.script_revision import BeatEvidence, ScriptIdentity, ScriptValidationResult
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()

_NARRATION_WPM = 130
_SYSTEM_PROMPT = build_7beat_system_prompt()
_EVIDENCE_DELIMITER = "---BEAT-EVIDENCE---"
_BEAT_NAMES = ("DISRUPT", "CHALLENGE", "PROVE", "REVEAL", "FRAME", "APPLY", "TRANSFORM")


def _parse_llm_response(text: str) -> tuple[str, dict]:
    """Split LLM output into (script, beat_evidence_dict).

    When the delimiter is absent (old scripts, fallback), returns (text, {}).
    Strips optional markdown code fence around the JSON block.
    """
    if _EVIDENCE_DELIMITER not in text:
        return text, {}
    script_part, _, evidence_part = text.partition(_EVIDENCE_DELIMITER)
    script = script_part.strip()
    evidence_text = evidence_part.strip()
    evidence_text = re.sub(r"^```(?:json)?\s*\n?", "", evidence_text)
    evidence_text = re.sub(r"\n?```\s*$", "", evidence_text).strip()
    try:
        raw = json.loads(evidence_text)
        if not isinstance(raw, dict):
            raise ValueError("Expected JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("AtmaRefinerPipeline: beat evidence parse failed ({})", exc)
        return script, {}
    evidence: dict = {}
    for beat in _BEAT_NAMES:
        if beat in raw and isinstance(raw[beat], dict):
            try:
                evidence[beat] = BeatEvidence.from_dict(raw[beat])
            except Exception:
                pass
    return script, evidence


def _load_beat_evidence(script_dir: Path) -> dict:
    """Load cached beat evidence from atma-beat-evidence.json; returns {} if absent."""
    evidence_file = script_dir / "atma-beat-evidence.json"
    if not evidence_file.exists():
        return {}
    try:
        raw = json.loads(evidence_file.read_text(encoding="utf-8"))
        evidence: dict = {}
        for beat in _BEAT_NAMES:
            if beat in raw and isinstance(raw[beat], dict):
                try:
                    evidence[beat] = BeatEvidence.from_dict(raw[beat])
                except Exception:
                    pass
        return evidence
    except Exception as exc:
        logger.warning("AtmaRefinerPipeline: failed to load beat evidence cache ({})", exc)
        return {}


class AtmaRefinerPipeline:
    """Edit a script to satisfy the 7-Beat Atma Theory narrative framework.

    The LLM is used exclusively as an editor — one call, surgical edits,
    ScriptIdentity as a hard constraint.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_for_task(settings, LLMTask.SCRIPT_REFINEMENT)
        # Use SCRIPT_JUDGE_MODEL when set; fall back to the QA task model.
        self._judge_llm = get_llm_for_role(
            settings,
            "script-judge",
            model_override=getattr(settings, "SCRIPT_JUDGE_MODEL", "") or "",
        )
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
        mode: str = "full",
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
            mode: "full" (default) runs the full 7-Beat editorial pass.
                "format" inserts pipeline markers and checks word count only —
                use for externally-reviewed scripts where content must not change.
                "passthrough" uses the base script exactly as-is — no LLM call,
                no edits, just validate and write for downstream.
        """
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        refined_file = script_dir / "atma-refined.md"

        # Idempotency: use cached output for initial refinement only.
        # Passthrough always re-writes — the base script is the truth, not the cache.
        is_targeted = bool(reviewer_feedback and current_refined)
        if not force and not is_targeted and mode != "passthrough" and refined_file.exists():
            cached = refined_file.read_text(encoding="utf-8")
            if cached.strip():
                console.print(
                    f"\n[dim]Atma Refiner: cached atma-refined.md exists — "
                    f"delete it to re-run (project: {project_id})[/dim]"
                )
                cached_evidence = _load_beat_evidence(script_dir)
                validation = self._validator.validate(
                    cached, identity, base_script, beat_evidence=cached_evidence or None
                )
                return cached, validation

        source_wc = (
            len(re.sub(r"\[[^\]]*\]", "", base_script).split()) if base_script else 0
        )

        # ── Path 1: Targeted refinement (human rejection feedback) ──────────────
        if is_targeted:
            label = "Targeted refinement (addressing reviewer feedback)"
            console.print(f"\n[bold magenta]✍  Atma Refiner[/bold magenta] — {label}...")
            prompt = build_targeted_refinement_prompt(
                current_refined_script=current_refined,  # type: ignore[arg-type]
                base_script=base_script,
                identity=identity,
                reviewer_feedback=reviewer_feedback,  # type: ignore[arg-type]
                beats=beats,
            )
            response = self._llm.generate(prompt, system_prompt=_SYSTEM_PROMPT, temperature=0.45)
            refined, beat_evidence = _parse_llm_response(response.text.strip())
            if not refined:
                logger.error("AtmaRefinerPipeline: LLM returned empty output — using base script")
                refined = base_script
                beat_evidence = {}
            _loop_result = None

        # ── Path 2: Format-only pass (marker insertion, no content rewrite) ────
        elif mode == "format":
            label = "Format pass — markers + word-count only (content preserved)"
            console.print(f"\n[bold magenta]✍  Atma Refiner[/bold magenta] — {label}...")
            prompt = build_format_pass_prompt(
                script_text=base_script,
                identity=identity,
                source_word_count=source_wc,
            )
            response = self._llm.generate(prompt, system_prompt=_SYSTEM_PROMPT, temperature=0.2)
            refined, beat_evidence = _parse_llm_response(response.text.strip())
            if not refined:
                logger.error("AtmaRefinerPipeline: LLM returned empty output — using base script")
                refined = base_script
                beat_evidence = {}
            _loop_result = None

        # ── Path 3: Passthrough — base script used exactly as-is ──────────────
        elif mode == "passthrough":
            label = "Passthrough — base script used as-is (no LLM call)"
            console.print(f"\n[bold magenta]✍  Atma Refiner[/bold magenta] — {label}...")
            refined = base_script
            beat_evidence = {}
            _loop_result = None

        # ── Path 4: Full 7-Beat refinement with judge-driven loop ──────────────
        else:
            label = "Initial 7-Beat refinement (judge-driven loop)"
            console.print(f"\n[bold magenta]✍  Atma Refiner[/bold magenta] — {label}...")

            _call_count = [0]
            _last_evidence: list[dict] = [{}]

            def _refiner_fn(current_script: str, feedback: str) -> str:  # noqa: E306
                _call_count[0] += 1
                if _call_count[0] == 1:
                    p = build_initial_refinement_prompt(
                        script_text=base_script,
                        identity=identity,
                        beats=beats,
                        target_minutes=target_minutes,
                        source_word_count=source_wc,
                    )
                else:
                    p = build_targeted_refinement_prompt(
                        current_refined_script=current_script,
                        base_script=base_script,
                        identity=identity,
                        reviewer_feedback=feedback,
                        beats=beats,
                    )
                resp = self._llm.generate(p, system_prompt=_SYSTEM_PROMPT, temperature=0.45)
                text, evidence = _parse_llm_response(resp.text.strip())
                _last_evidence[0] = evidence
                return text if text else current_script

            concepts = list(getattr(identity, "strong_original_ideas", None) or [])
            judge = ScriptJudge(self._judge_llm)
            loop = RefinementLoop(judge, _refiner_fn)
            _loop_result = loop.run(base_script, identity, concepts_to_preserve=concepts)

            refined = _loop_result.script
            beat_evidence = _last_evidence[0]
            if not refined:
                logger.error("AtmaRefinerPipeline: loop returned empty script — using base script")
                refined = base_script
                beat_evidence = {}

            console.print(
                f"  [dim]Loop: {_loop_result.iterations_used} iteration(s), "
                f"best attempt={_loop_result.accepted_attempt}, "
                f"status={_loop_result.overall_status}[/dim]"
            )

        words = len(refined.split())
        estimated_min = words / _NARRATION_WPM
        console.print(f"  [dim]Refined:[/dim] {words} words (~{estimated_min:.1f} min)")

        # Validate before returning to human review
        validation = self._validator.validate(
            refined, identity, base_script, beat_evidence=beat_evidence or None
        )

        # Write outputs — skip caching atma-refined.md on judge_failure so the
        # idempotency check doesn't serve a stale fallback on the next run.
        _is_judge_failure = (
            _loop_result is not None and _loop_result.overall_status == "judge_failure"
        )
        if not _is_judge_failure:
            refined_file.write_text(refined, encoding="utf-8")
        if beat_evidence:
            evidence_file = script_dir / "atma-beat-evidence.json"
            evidence_file.write_text(
                json.dumps(
                    {k: v.to_dict() for k, v in beat_evidence.items()},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        report_path = script_dir / "atma-refinement-report.json"
        _mode_label = "targeted" if is_targeted else ("format" if mode == "format" else "full")
        report_data: dict = {
            "mode": _mode_label,
            "target_minutes": target_minutes,
            "word_count": words,
            "estimated_minutes": round(estimated_min, 2),
            "validation": validation.to_dict(),
            "reviewer_feedback": reviewer_feedback,
        }
        if _loop_result is not None:
            report_data["refinement_loop"] = _loop_result.to_dict()
        report_path.write_text(
            json.dumps(report_data, indent=2, ensure_ascii=False),
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
