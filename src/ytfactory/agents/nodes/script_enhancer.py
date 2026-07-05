"""Script Enhancer node — rewrites a raw user script into a cinematic professional narration."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.branding import get_closing, get_transition, get_welcome
from ytfactory.agents.prompts.script_enhancer import build_enhance_script_prompt
from ytfactory.agents.prompts.script_writer import (
    DURATION_TOLERANCE_MINUTES,
    NARRATION_WPM,
    TARGET_IDEAL_MINUTES,
)
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


def _duration_ok(estimated_minutes: float, target_minutes: int) -> bool:
    return abs(estimated_minutes - target_minutes) <= DURATION_TOLERANCE_MINUTES


def script_enhancer_node(state: VideoState) -> dict:
    """
    Transforms the raw user-provided script into a beautiful, cinematic narration.

    V2 pacing rules: preserves the base script as source of truth, prefers
    slower pacing over adding filler, and validates duration within ±1 min
    of the requested target.

    The enhanced script is what the scene planner uses to extract narrations,
    and those narrations go directly into TTS audio.
    """
    settings = Settings()
    llm = get_llm_provider(settings)

    topic = state["topic"]
    project_id = state["project_id"]
    style = state.get("style")
    raw_script = state.get("script_md", "")
    target_minutes: int = int(state.get("target_minutes", TARGET_IDEAL_MINUTES))

    min_minutes = target_minutes - DURATION_TOLERANCE_MINUTES
    max_minutes = target_minutes + DURATION_TOLERANCE_MINUTES

    style_label = f" [{style}]" if style else ""
    console.print(
        f"\n[bold magenta]✍  Script Enhancer[/bold magenta]{style_label} — "
        f"transforming script into cinematic narration "
        f"(target: {target_minutes} min ±{DURATION_TOLERANCE_MINUTES} min)..."
    )

    raw_words = len(raw_script.split())
    target_words = target_minutes * NARRATION_WPM
    console.print(
        f"  [dim]Input:[/dim] {raw_words} words → target {target_minutes} min "
        f"(~{target_words} words, range {min_minutes}–{max_minutes} min)"
    )

    prompt = build_enhance_script_prompt(
        topic,
        raw_script,
        style,
        target_minutes=target_minutes,
        welcome=get_welcome(),
        closing=get_closing(),
        topic_transition=get_transition(),
    )
    response = llm.generate(prompt, temperature=0.6)
    enhanced_script = response.text.strip()

    enhanced_words = len(enhanced_script.split())
    enhanced_est = enhanced_words / NARRATION_WPM
    console.print(
        f"  [green]✓[/green] Enhanced: {enhanced_words} words "
        f"(~{enhanced_est:.1f} min at 130 wpm)"
    )

    # ── Duration validation ───────────────────────────────────────────────
    ok = _duration_ok(enhanced_est, target_minutes)
    gap = enhanced_est - target_minutes
    if ok:
        console.print(
            f"  [green]✓ DURATION PASS[/green] — "
            f"{enhanced_est:.1f} min (target {target_minutes} min, gap {gap:+.1f} min)"
        )
    else:
        direction = "over" if gap > 0 else "under"
        console.print(
            f"  [yellow]⚠ DURATION WARN[/yellow] — "
            f"{enhanced_est:.1f} min is {abs(gap):.1f} min {direction} target "
            f"(tolerance ±{DURATION_TOLERANCE_MINUTES} min)"
        )

    logger.info(
        "Script enhanced: {} → {} words (~{:.1f} min), target {} min, ok={}",
        raw_words,
        enhanced_words,
        enhanced_est,
        target_minutes,
        ok,
    )

    # Save both versions to workspace
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)

    # Keep the original for reference
    (script_dir / "script_original.md").write_text(raw_script, encoding="utf-8")
    # Enhanced version is the one used downstream
    (script_dir / "script.md").write_text(enhanced_script, encoding="utf-8")

    # Persist diagnostics
    import json

    (script_dir / "script.json").write_text(
        json.dumps(
            {
                "topic": topic,
                "word_count": enhanced_words,
                "estimated_minutes": round(enhanced_est, 2),
                "target_minutes": target_minutes,
                "tolerance_minutes": DURATION_TOLERANCE_MINUTES,
                "duration_ok": ok,
                "gap_minutes": round(gap, 2),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    status_color = "green" if ok else "yellow"
    console.print(
        Panel(
            f"[{status_color}]Script ready[/{status_color}] — {enhanced_words} words, "
            f"~{enhanced_est:.1f} min (target {target_minutes} min)\n"
            f"[dim]Original saved to script_original.md[/dim]",
            title="Script Enhancer",
            border_style="magenta",
        )
    )

    return {"script_md": enhanced_script}
