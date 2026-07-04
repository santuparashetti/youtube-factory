"""Script writer agent node — converts research into a narration script."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.branding import get_closing, get_transition, get_welcome
from ytfactory.agents.prompts.script_writer import (
    COMPRESS_SCRIPT,
    SELF_REVIEW_SCRIPT,
    TARGET_IDEAL_WORDS,
    TARGET_MAX_WORDS,
    TARGET_MIN_WORDS,
    WRITE_SCRIPT,
)
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository

console = Console()


def _word_count(text: str) -> int:
    return len(text.split())


def _estimated_minutes(word_count: int) -> float:
    return word_count / 130


def script_writer_node(state: VideoState) -> dict:
    """
    Script Writer Agent:
    1. Write first-draft script (9-section structure, density rules enforced in prompt)
    2. Self-review: quality checklist + duration enforcement + auto-compress if needed
    3. Safety compression: if still over 10 min after review, explicit compress pass
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
    console.print(
        f"\n[bold cyan]✍️  Script Writer Agent[/bold cyan] — "
        f"writing script for: [italic]{topic}[/italic]\n"
    )

    # Load outline if available (written by research node)
    outline_path = Path(WORKSPACE_DIR) / project_id / "research" / "script_outline.md"
    script_outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""

    # ── Step 1: Write first-draft script ─────────────────────────────────
    welcome = get_welcome()
    closing = get_closing()
    topic_transition = get_transition()

    script_response = llm.generate(
        WRITE_SCRIPT.format(
            topic=topic,
            research_md=research_md,
            script_outline=script_outline,
            welcome=welcome,
            closing=closing,
            topic_transition=topic_transition,
        ),
        temperature=0.6,
    )
    script = script_response.text.strip()
    wc = _word_count(script)
    est_min = _estimated_minutes(wc)
    console.print(
        f"  [green]✓[/green] First draft: {wc} words "
        f"(~{est_min:.1f} min, target 7–8 min)"
    )

    # ── Step 2: Self-review — quality checklist + duration enforcement ────
    review_response = llm.generate(
        SELF_REVIEW_SCRIPT.format(
            topic=topic,
            script=script,
            word_count=wc,
            estimated_minutes=est_min,
        ),
        temperature=0.4,
    )
    reviewed = review_response.text.strip()
    reviewed_wc = _word_count(reviewed)

    if reviewed_wc < 50:
        # Review returned something degenerate — keep original
        reviewed = script
        reviewed_wc = wc

    reviewed_est = _estimated_minutes(reviewed_wc)
    console.print(
        f"  [green]✓[/green] After review: {reviewed_wc} words "
        f"(~{reviewed_est:.1f} min)"
    )

    # ── Step 3: Safety compression — catches cases where review didn't ────
    final_script = reviewed
    final_wc = reviewed_wc

    if final_wc > TARGET_MAX_WORDS:
        console.print(
            f"  [yellow]![/yellow] Over limit ({final_wc} words > {TARGET_MAX_WORDS}) "
            f"— compressing..."
        )
        compress_response = llm.generate(
            COMPRESS_SCRIPT.format(
                script=final_script,
                word_count=final_wc,
                estimated_minutes=_estimated_minutes(final_wc),
                target_max_words=TARGET_MAX_WORDS,
                target_ideal_words=TARGET_IDEAL_WORDS,
            ),
            temperature=0.3,
        )
        compressed = compress_response.text.strip()
        compressed_wc = _word_count(compressed)
        if compressed_wc >= TARGET_MIN_WORDS:
            final_script = compressed
            final_wc = compressed_wc
            console.print(
                f"  [green]✓[/green] Compressed: {final_wc} words "
                f"(~{_estimated_minutes(final_wc):.1f} min)"
            )

    final_est = _estimated_minutes(final_wc)

    # ── Persist ───────────────────────────────────────────────────────────
    artifact_repo.write_markdown(project_id, "script", "script.md", final_script)
    artifact_repo.write_json(
        project_id,
        "script",
        "script.json",
        {
            "topic": topic,
            "word_count": final_wc,
            "estimated_minutes": round(final_est, 2),
            "target_min_minutes": 5,
            "target_ideal_minutes": 8,
            "target_max_minutes": 10,
        },
    )

    project_repo.update_stage(project_id, "script", "completed")
    console.print(Panel(
        f"[green]Script complete[/green] — {final_wc} words, "
        f"~{final_est:.1f} minutes",
        title="Script Writer Agent",
        border_style="green",
    ))

    return {"script_md": final_script}
