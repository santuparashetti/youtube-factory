"""Script writer agent node — converts research into a narration script."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.script_writer import SELF_REVIEW_SCRIPT, WRITE_SCRIPT
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository

console = Console()

_TARGET_MINUTES = 4
_TARGET_WORDS = _TARGET_MINUTES * 130  # ~130 wpm narration pace


def _word_count(text: str) -> int:
    return len(text.split())


def script_writer_node(state: VideoState) -> dict:
    """
    Script Writer Agent:
    1. Read research.md + script_outline.md from workspace
    2. Generate full narration script
    3. Self-review: if hook/pacing is weak, regenerate
    4. Save to workspace/jobs/{id}/script/script.md
    """
    settings = Settings()
    llm = get_llm_provider(settings)
    artifact_repo = ArtifactRepository()
    project_repo = ProjectRepository()

    topic = state["topic"]
    project_id = state["project_id"]
    research_md = state.get("research_md", "")

    project_repo.update_stage(project_id, "script", "running")
    console.print(f"\n[bold cyan]✍️  Script Writer Agent[/bold cyan] — writing script for: [italic]{topic}[/italic]\n")

    # Load outline if available (written by research node)
    outline_path = Path(WORKSPACE_DIR) / project_id / "research" / "script_outline.md"
    script_outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""

    # ── Step 1: Write first-draft script ─────────────────────────────────
    script_response = llm.generate(
        WRITE_SCRIPT.format(
            topic=topic,
            target_words=_TARGET_WORDS,
            target_minutes=_TARGET_MINUTES,
            research_md=research_md,
            script_outline=script_outline,
        ),
        temperature=0.6,
    )
    script = script_response.text.strip()
    wc = _word_count(script)
    console.print(f"  [green]✓[/green] First draft: {wc} words (target {_TARGET_WORDS})")

    # ── Step 2: Self-review and improve ──────────────────────────────────
    review_response = llm.generate(
        SELF_REVIEW_SCRIPT.format(
            topic=topic,
            script=script,
            word_count=wc,
            target_words=_TARGET_WORDS,
        ),
        temperature=0.4,
    )
    final_script = review_response.text.strip()
    final_wc = _word_count(final_script)

    if final_wc < 50:
        # Self-review returned something too short — keep original
        final_script = script
        final_wc = wc

    console.print(f"  [green]✓[/green] Final script: {final_wc} words (~{final_wc // 130} min)")

    # ── Persist ───────────────────────────────────────────────────────────
    artifact_repo.write_markdown(project_id, "script", "script.md", final_script)
    artifact_repo.write_json(
        project_id,
        "script",
        "script.json",
        {"topic": topic, "word_count": final_wc, "estimated_minutes": final_wc / 130},
    )

    project_repo.update_stage(project_id, "script", "completed")
    console.print(Panel(
        f"[green]Script complete[/green] — {final_wc} words, "
        f"~{final_wc / 130:.1f} minutes",
        title="Script Writer Agent",
        border_style="green",
    ))

    return {"script_md": final_script}
