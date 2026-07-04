"""Script Enhancer node — rewrites a raw user script into a cinematic professional narration."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.branding import get_closing, get_transition, get_welcome
from ytfactory.agents.prompts.script_enhancer import build_enhance_script_prompt
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR

console = Console()


def script_enhancer_node(state: VideoState) -> dict:
    """
    Transforms the raw user-provided script into a beautiful, cinematic narration.

    The enhanced script is what the scene planner uses to extract narrations,
    and those narrations go directly into TTS audio — so quality here flows
    through to every word spoken in the final video.
    """
    settings = Settings()
    llm = get_llm_provider(settings)

    topic = state["topic"]
    project_id = state["project_id"]
    style = state.get("style")
    raw_script = state.get("script_md", "")
    target_minutes: int = state.get("target_minutes", 7)

    style_label = f" [{style}]" if style else ""
    console.print(
        f"\n[bold magenta]✍  Script Enhancer[/bold magenta]{style_label} — "
        f"transforming script into cinematic narration..."
    )

    raw_words = len(raw_script.split())
    target_words = int(target_minutes * 130)
    console.print(
        f"  [dim]Input:[/dim] {raw_words} words → target {target_minutes} min "
        f"(~{target_words} words)"
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
    console.print(
        f"  [green]✓[/green] Enhanced: {enhanced_words} words "
        f"(~{enhanced_words / 130:.1f} min at 130 wpm)"
    )

    # Save both versions to workspace
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)

    # Keep the original for reference
    (script_dir / "script_original.md").write_text(raw_script, encoding="utf-8")
    # Enhanced version is the one used downstream
    (script_dir / "script.md").write_text(enhanced_script, encoding="utf-8")

    logger.info("Script enhanced: {} → {} words", raw_words, enhanced_words)

    console.print(Panel(
        f"[green]Script ready[/green] — {enhanced_words} words, "
        f"~{enhanced_words / 130:.1f} min\n"
        f"[dim]Original saved to script_original.md[/dim]",
        title="Script Enhancer",
        border_style="magenta",
    ))

    return {"script_md": enhanced_script}
