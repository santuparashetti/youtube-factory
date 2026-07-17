"""Light Normalization Pipeline — clean transcript artifacts before documentary enhancement.

Responsibilities (exactly):
  - Remove ASR artifacts (immediate word stutters, isolated fillers)
  - Normalize whitespace and punctuation
  - Preserve scripture / Sanskrit / sacred text spans byte-for-byte
  - Flag (not resolve) ambiguous spans for downstream review
  - Validate output against four automated checks from ADR-0010

Explicitly NOT this stage's job:
  - Rewriting, improving, summarizing, or restructuring content
  - Converting discourse into documentary narrative
  - Changing tone, pacing, or emotional intensity
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.light_normalization import build_light_normalization_prompt
from ytfactory.config.settings import Settings
from ytfactory.shared.scripture import (
    extract_scripture_spans,
    restore_scripture_spans,
)
from video_core.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR

from .validator import NormalizationValidator, ValidationResult

console = Console()


# Scripture extraction is provided by ytfactory.shared.scripture
# (extract_scripture_spans, restore_scripture_spans imported above)


# ── Pipeline ───────────────────────────────────────────────────────────────────


class LightNormalizationPipeline:
    """Clean transcript artifacts before the Documentary Script Enhancer.

    Input:  workspace/jobs/<id>/script/script.md   (raw transcript)
    Output: workspace/jobs/<id>/script/script.md   (normalized, in-place)
    Backup: workspace/jobs/<id>/script/script_pre_normalize.md
    Report: workspace/jobs/<id>/script/normalization-report.json
    """

    def __init__(self, settings: Settings) -> None:
        self._llm = get_llm_provider(settings)
        self._validator = NormalizationValidator()

    def run(
        self,
        project_id: str,
        *,
        script_text: str | None = None,
    ) -> str:
        """Normalize a transcript and return the normalized text.

        Args:
            project_id: Used to locate/write workspace files.
            script_text: Raw transcript. When None, read from script/script.md.
        """
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)

        if script_text is None:
            script_file = script_dir / "script.md"
            if not script_file.exists():
                raise FileNotFoundError(
                    f"LightNormalizationPipeline: no script at {script_file}"
                )
            script_text = script_file.read_text(encoding="utf-8")

        raw_words = len(script_text.split())
        console.print(
            f"\n[bold cyan]✦  Light Normalization[/bold cyan] — "
            f"{raw_words} words input"
        )

        # Protect scripture spans from LLM
        placeholder_text, placeholders = extract_scripture_spans(script_text)
        if placeholders:
            console.print(
                f"  [dim]Detected {len(placeholders)} scripture span(s) — protected from modification[/dim]"
            )

        # LLM normalization pass
        prompt = build_light_normalization_prompt(placeholder_text, placeholders)
        response = self._llm.generate(prompt, temperature=0.0)
        normalized_with_placeholders = response.text.strip()

        # Validate before restoring scripture
        validation = self._validator.validate(
            original=placeholder_text,
            normalized=normalized_with_placeholders,
            scripture_spans=list(placeholders.values()),
        )

        _log_validation(validation)

        if not validation.passed:
            logger.warning(
                "LightNormalization: validation failed — using original transcript as fallback. "
                "Errors: {}",
                validation.errors,
            )
            console.print(
                "[yellow]⚠ Validation failed — falling back to original (unfailed) transcript[/yellow]"
            )
            # Fallback: use the original (after restoring any placeholders from the original)
            normalized_final = script_text
        else:
            # Restore scripture spans
            normalized_final = restore_scripture_spans(
                normalized_with_placeholders, placeholders
            )

        # Count flags left by LLM
        flags = re.findall(r"\[FLAG:", normalized_final)
        if flags:
            console.print(
                f"  [yellow]⚠ {len(flags)} ambiguous span(s) flagged for review "
                f"([FLAG:...][/FLAG] markers in output)[/yellow]"
            )

        out_words = len(normalized_final.split())
        console.print(
            f"  [green]✓[/green] {raw_words} → {out_words} words "
            f"(change ratio: {validation.change_ratio:.1%})"
        )

        # Write outputs
        (script_dir / "script_pre_normalize.md").write_text(
            script_text, encoding="utf-8"
        )
        (script_dir / "script.md").write_text(normalized_final, encoding="utf-8")

        report = {
            "passed": validation.passed,
            "change_ratio": round(validation.change_ratio, 4),
            "checks": validation.checks,
            "errors": validation.errors,
            "warnings": validation.warnings,
            "scripture_spans_detected": len(placeholders),
            "ambiguous_flags": len(flags),
            "input_words": raw_words,
            "output_words": out_words,
            "fallback_used": not validation.passed,
        }
        (script_dir / "normalization-report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

        status_color = "green" if validation.passed else "yellow"
        console.print(
            Panel(
                f"[{status_color}]Normalization complete[/{status_color}] — "
                f"{out_words} words, change ratio {validation.change_ratio:.1%}\n"
                f"[dim]Original saved to script_pre_normalize.md[/dim]",
                title="Light Normalization",
                border_style="cyan",
            )
        )

        logger.info(
            "Light normalization: {} → {} words, change_ratio={:.1%}, passed={}, fallback={}",
            raw_words,
            out_words,
            validation.change_ratio,
            validation.passed,
            not validation.passed,
        )

        return normalized_final


def _log_validation(v: ValidationResult) -> None:
    for err in v.errors:
        logger.error("LightNormalization validation: {}", err)
    for warn in v.warnings:
        logger.warning("LightNormalization validation: {}", warn)
