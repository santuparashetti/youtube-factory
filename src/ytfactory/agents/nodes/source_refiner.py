"""Source refiner node — editorial pass on the base script before composition."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from rich.console import Console

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.source_refiner.pipeline import SourceRefinerPipeline

console = Console()


def source_refiner_node(state: VideoState) -> dict:
    """Run the editorial refinement pass on the base script.

    Idempotency checkpoint: if script_pre_refiner.md already exists, the full
    generation pipeline (refiner + composer) has already run on this project.
    Skip all LLM calls and load script.md directly so the composer node (which
    has its own checkpoint) also skips — allowing a rerun after a manual script
    edit to proceed straight to scene planning without regenerating anything.

    Fall-through to full generation when:
    - script_pre_refiner.md does not exist (fresh import, first run)
    - script.md is missing or empty despite the backup existing (corrupted state)
    """
    project_id = state["project_id"]
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_file = script_dir / "script.md"
    backup_file = script_dir / "script_pre_refiner.md"

    if backup_file.exists():
        if script_file.exists():
            content = script_file.read_text(encoding="utf-8").strip()
            if content:
                logger.info(
                    "SourceRefiner: script already processed — skipping generation, "
                    "loading from script.md (delete script_pre_refiner.md to re-run)"
                )
                console.print(
                    "\n[dim]Source Refiner skipped — script already exists, "
                    f"loading from file "
                    f"(delete workspace/jobs/{project_id}/script/script_pre_refiner.md "
                    f"to re-run generation)[/dim]"
                )
                return {"script_md": content}
        logger.warning(
            "SourceRefiner: script_pre_refiner.md exists but script.md is missing "
            "or empty — falling through to full generation"
        )
        console.print(
            "[yellow]⚠ Source Refiner: backup exists but script.md is empty/missing "
            "— running full generation[/yellow]"
        )

    beats = state.get("beats") or []
    settings = Settings()
    pipeline = SourceRefinerPipeline(settings)
    refined = pipeline.run(project_id, beats=beats)
    return {"script_md": refined}
