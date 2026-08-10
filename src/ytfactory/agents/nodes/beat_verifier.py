"""Beat verifier node — observability pass after composition/recomposition.

Runs after script_selector_polisher (or directly after composer in the A/B path)
and before human_review_final_script. Non-blocking: logs and writes
beat-verification.json but never stops the pipeline.
"""

from __future__ import annotations

from loguru import logger
from rich.console import Console

from ytfactory.agents.state import VideoState
from ytfactory.composer.beat_verifier import verify_beats
from ytfactory.config.settings import Settings
from video_core.providers.llm.factory import get_llm_for_role

console = Console()


def beat_verifier_node(state: VideoState) -> dict:
    """Verify that all extracted beats survived the composition pipeline.

    Reads `beats` and `script_md` from state. Observability only — no
    state mutations, no blocking. Returns an empty dict so the graph can
    proceed to human_review_final_script unchanged.
    """
    project_id = state["project_id"]
    beats = state.get("beats") or []
    script = (
        state.get("selected_script")
        or state.get("script_md")
        or ""
    )

    if not beats:
        logger.info("BeatVerifier node: no beats in state — skipping verification")
        return {}

    if not script.strip():
        logger.warning("BeatVerifier node: no final script in state — skipping verification")
        return {}

    console.print("\n[dim]⟡  Beat Verifier — checking beat preservation...[/dim]")

    try:
        settings = Settings()
        provider = get_llm_for_role(settings, "source_refiner")
        result = verify_beats(script, beats, provider, project_id)
        if result.get("error") or result.get("skipped"):
            console.print("  [dim]Beat verification: skipped (see logs)[/dim]")
        else:
            missing = result.get("missing_count", 0)
            beat_results = result.get("beats", [])
            total = len(beat_results) if beat_results else len(beats)
            if missing == 0:
                console.print(f"  [green]✓[/green] Beat verification: {total}/{total} beats present")
            else:
                console.print(
                    f"  [yellow]⚠[/yellow] Beat verification: {total - missing}/{total} beats present "
                    f"({missing} missing — see beat-verification.json)"
                )
    except Exception as exc:
        logger.warning("BeatVerifier node failed ({}), continuing pipeline", exc)

    return {}
