"""Scene planner agent node — JSON validation loop + visual prompt enhancement."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ytfactory.agents.prompts.scene_planner import (
    ENHANCE_VISUAL_PROMPTS,
    FIX_JSON_PROMPT,
    PLAN_SCENES,
)
from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.providers.llm.factory import get_llm_provider
from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.storage.artifact_repository import ArtifactRepository
from ytfactory.storage.project_repository import ProjectRepository

console = Console()

_MAX_PARSE_RETRIES = 3


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM JSON responses."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        text = "\n".join(lines[start:end])
    return text.strip()


def _parse_scene_plan(text: str) -> dict | None:
    """Parse and validate a scene plan JSON response."""
    try:
        data = json.loads(_strip_fences(text))
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None
    if "scenes" not in data or not isinstance(data["scenes"], list):
        return None
    if not data["scenes"]:
        return None

    required = {"index", "title", "narration", "visual_prompt", "duration_seconds"}
    for scene in data["scenes"]:
        if not required.issubset(scene.keys()):
            return None

    return data


def scene_planner_node(state: VideoState) -> dict:
    """
    Scene Planner Agent:
    1. Load script from state / disk
    2. Generate scene plan JSON with retry loop on parse failure
    3. Validate and fix duration totals
    4. Second-pass: enhance visual prompts with cinematography guidance
    5. Save scene-plan.json + scene-plan.md
    """
    settings = Settings()
    llm = get_llm_provider(settings)
    artifact_repo = ArtifactRepository()
    project_repo = ProjectRepository()

    topic = state["topic"]
    project_id = state["project_id"]

    # Load script — prefer state, fall back to disk
    script_md = state.get("script_md", "")
    if not script_md:
        script_path = Path(WORKSPACE_DIR) / project_id / "script" / "script.md"
        if not script_path.exists():
            raise FileNotFoundError("Script not found. Run script-writer first.")
        script_md = script_path.read_text(encoding="utf-8")

    project_repo.update_stage(project_id, "scenes", "running")
    console.print(f"\n[bold cyan]🎬 Scene Planner Agent[/bold cyan] — planning scenes for: [italic]{topic}[/italic]\n")

    # ── Step 1: Generate scene plan (with JSON retry loop) ────────────────
    prompt = PLAN_SCENES.format(topic=topic, script=script_md)
    scene_plan: dict | None = None
    last_response_text = ""

    for attempt in range(1, _MAX_PARSE_RETRIES + 1):
        response = llm.generate(prompt, temperature=0.2)
        last_response_text = response.text
        scene_plan = _parse_scene_plan(last_response_text)

        if scene_plan:
            console.print(f"  [green]✓[/green] Scene plan parsed on attempt {attempt}")
            break

        if attempt < _MAX_PARSE_RETRIES:
            console.print(f"  [yellow]⚠[/yellow] JSON parse failed (attempt {attempt}), asking LLM to fix...")
            prompt = FIX_JSON_PROMPT.format(broken_json=last_response_text)
        else:
            raise ValueError(
                f"Scene planner failed to produce valid JSON after {_MAX_PARSE_RETRIES} attempts.\n"
                f"Last response:\n{last_response_text[:500]}"
            )

    assert scene_plan is not None
    scenes = scene_plan["scenes"]

    # ── Step 2: Duration sanity check ────────────────────────────────────
    total = sum(s.get("duration_seconds", 0) for s in scenes)
    scene_plan["total_duration_seconds"] = total
    console.print(f"  [green]✓[/green] {len(scenes)} scenes, total duration: {total:.0f}s (~{total/60:.1f} min)")

    # ── Step 3: Enhance visual prompts ────────────────────────────────────
    console.print("  [cyan]→[/cyan] Enhancing visual prompts for cinematic consistency...")
    enhance_response = llm.generate(
        ENHANCE_VISUAL_PROMPTS.format(
            topic=topic,
            scene_json=json.dumps({"scenes": scenes}, ensure_ascii=False, indent=2),
        ),
        temperature=0.3,
    )
    enhanced = _parse_scene_plan(enhance_response.text)
    if enhanced and len(enhanced["scenes"]) == len(scenes):
        for orig, enh in zip(scenes, enhanced["scenes"]):
            if enh.get("visual_prompt"):
                orig["visual_prompt"] = enh["visual_prompt"]
        console.print("  [green]✓[/green] Visual prompts enhanced")
    else:
        logger.warning("Visual prompt enhancement returned malformed JSON; keeping originals")

    # ── Persist artifacts ─────────────────────────────────────────────────
    artifact_repo.write_json(project_id, "scenes", "scene-plan.json", scene_plan)

    # Human-readable markdown summary
    md_lines = [f"# Scene Plan: {topic}\n", f"Total: {len(scenes)} scenes, ~{total/60:.1f} min\n"]
    for s in scenes:
        md_lines.append(
            f"## Scene {s['index']}: {s['title']} ({s['duration_seconds']}s)\n"
            f"**Narration:** {s['narration']}\n\n"
            f"**Visual:** {s['visual_prompt']}\n"
        )
    artifact_repo.write_markdown(project_id, "scenes", "scene-plan.md", "\n".join(md_lines))

    project_repo.update_stage(project_id, "scenes", "completed")

    # Print summary table
    table = Table(title="Scene Plan", show_lines=True)
    table.add_column("#", style="cyan", width=4)
    table.add_column("Title", style="bold")
    table.add_column("Duration", width=8)
    table.add_column("Narration preview", max_width=50)
    for s in scenes:
        narration_preview = s["narration"][:60] + "…" if len(s["narration"]) > 60 else s["narration"]
        table.add_row(str(s["index"]), s["title"], f"{s['duration_seconds']}s", narration_preview)
    console.print(table)
    console.print(Panel(
        f"[green]Scene plan complete[/green] — {len(scenes)} scenes, ~{total/60:.1f} minutes",
        title="Scene Planner Agent",
        border_style="green",
    ))

    return {"scene_plan": scenes}
