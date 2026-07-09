"""Script writer agent node — converts research into a narration script."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ytfactory.agents.prompts.branding import (
    get_closing,
    get_closing_brand,
    get_transition,
    get_welcome,
)
from ytfactory.agents.prompts.script_writer import (
    DURATION_TOLERANCE_MINUTES,
    NARRATION_WPM,
    TARGET_IDEAL_MINUTES,
    TARGET_MIN_WORDS,
    build_compress_prompt,
    build_expand_pacing_prompt,
    build_review_prompt,
    build_write_script_prompt,
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
    return word_count / NARRATION_WPM


def _duration_ok(estimated: float, target: int) -> bool:
    return abs(estimated - target) <= DURATION_TOLERANCE_MINUTES


def script_writer_node(state: VideoState) -> dict:
    """
    Script Writer Agent — V2 pacing and duration rules:
    1. Write first-draft script (9-section structure, density rules enforced in prompt)
    2. Self-review: quality checklist + duration enforcement + auto-compress if needed
    3. Safety pass: compress if still over target+1min, or expand-with-pacing if under target-1min
    4. Duration validation: log PASS/FAIL diagnostic, persist duration_ok in script.json
    5. Save to workspace/jobs/{id}/script/script.md
    """
    settings = Settings()
    llm = get_llm_provider(settings)
    artifact_repo = ArtifactRepository()
    project_repo = ProjectRepository()

    topic = state["topic"]
    project_id = state["project_id"]
    research_md = state.get("research_md", "")
    target_minutes: int = int(state.get("target_minutes", TARGET_IDEAL_MINUTES))

    max_minutes = target_minutes + DURATION_TOLERANCE_MINUTES
    min_minutes = target_minutes - DURATION_TOLERANCE_MINUTES
    max_words = max_minutes * NARRATION_WPM

    project_repo.update_stage(project_id, "script", "running")
    console.print(
        f"\n[bold cyan]✍️  Script Writer Agent[/bold cyan] — "
        f"writing script for: [italic]{topic}[/italic] "
        f"(target: {target_minutes} min ±{DURATION_TOLERANCE_MINUTES} min)\n"
    )

    # Load outline if available (written by research node)
    outline_path = Path(WORKSPACE_DIR) / project_id / "research" / "script_outline.md"
    script_outline = (
        outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
    )

    # ── Step 1: Write first-draft script ─────────────────────────────────
    welcome = get_welcome()
    closing = get_closing()
    closing_brand = get_closing_brand()
    topic_transition = get_transition()

    script_response = llm.generate(
        build_write_script_prompt(
            topic=topic,
            research_md=research_md,
            script_outline=script_outline,
            welcome=welcome,
            closing=closing,
            topic_transition=topic_transition,
            target_minutes=target_minutes,
            closing_brand=closing_brand,
        ),
        temperature=0.6,
    )
    script = script_response.text.strip()
    wc = _word_count(script)
    est_min = _estimated_minutes(wc)
    console.print(
        f"  [green]✓[/green] First draft: {wc} words "
        f"(~{est_min:.1f} min, target {target_minutes} min)"
    )

    # ── Step 2: Self-review — quality checklist + duration enforcement ────
    review_response = llm.generate(
        build_review_prompt(
            topic=topic,
            script=script,
            word_count=wc,
            estimated_minutes=est_min,
            target_minutes=target_minutes,
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

    # ── Step 3: Safety pass — compress if over, expand-with-pacing if under ──
    final_script = reviewed
    final_wc = reviewed_wc
    final_est = reviewed_est

    if final_wc > max_words:
        console.print(
            f"  [yellow]![/yellow] Over limit ({final_wc} words > {max_words}) "
            f"— compressing..."
        )
        compress_response = llm.generate(
            build_compress_prompt(
                script=final_script,
                word_count=final_wc,
                estimated_minutes=final_est,
                target_minutes=target_minutes,
            ),
            temperature=0.3,
        )
        compressed = compress_response.text.strip()
        compressed_wc = _word_count(compressed)
        if compressed_wc >= TARGET_MIN_WORDS:
            final_script = compressed
            final_wc = compressed_wc
            final_est = _estimated_minutes(final_wc)
            console.print(
                f"  [green]✓[/green] Compressed: {final_wc} words "
                f"(~{final_est:.1f} min)"
            )

    elif final_est < min_minutes:
        console.print(
            f"  [yellow]![/yellow] Under target ({final_est:.1f} min < {min_minutes} min) "
            f"— applying pacing adjustments..."
        )
        expand_response = llm.generate(
            build_expand_pacing_prompt(
                script=final_script,
                word_count=final_wc,
                estimated_minutes=final_est,
                target_minutes=target_minutes,
            ),
            temperature=0.4,
        )
        expanded = expand_response.text.strip()
        expanded_wc = _word_count(expanded)
        if expanded_wc > final_wc:
            final_script = expanded
            final_wc = expanded_wc
            final_est = _estimated_minutes(final_wc)
            console.print(
                f"  [green]✓[/green] After pacing: {final_wc} words "
                f"(~{final_est:.1f} min)"
            )

    # ── Step 4: Duration validation ───────────────────────────────────────
    ok = _duration_ok(final_est, target_minutes)
    gap = final_est - target_minutes
    if ok:
        console.print(
            f"  [green]✓ DURATION PASS[/green] — "
            f"{final_est:.1f} min (target {target_minutes} min, gap {gap:+.1f} min)"
        )
    else:
        direction = "over" if gap > 0 else "under"
        console.print(
            f"  [yellow]⚠ DURATION WARN[/yellow] — "
            f"{final_est:.1f} min is {abs(gap):.1f} min {direction} target "
            f"(tolerance ±{DURATION_TOLERANCE_MINUTES} min)"
        )

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
            "target_minutes": target_minutes,
            "tolerance_minutes": DURATION_TOLERANCE_MINUTES,
            "duration_ok": ok,
            "gap_minutes": round(gap, 2),
        },
    )

    project_repo.update_stage(project_id, "script", "completed")
    status_color = "green" if ok else "yellow"
    console.print(
        Panel(
            f"[{status_color}]Script complete[/{status_color}] — {final_wc} words, "
            f"~{final_est:.1f} min (target {target_minutes} min)",
            title="Script Writer Agent",
            border_style=status_color,
        )
    )

    return {"script_md": final_script}
