"""Interactive CLI wizard — default experience when ytfactory is run with no subcommand."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import questionary
from rich.console import Console
from rich.panel import Panel

console = Console()

# ── Option tables ─────────────────────────────────────────────────────────────

_PRESETS = [
    "🆕  New Project (Phase 1)",
    "▶️   Resume Project (Phase 2)",
    "🔄  Re-plan Scenes (keep script)",
    "✂️   Generate Shorts (Phase 1 — extract + script + scene plan)",
    "📱  Render Shorts Video (Phase 2 — images → TTS → video)",
    "🎬  Full AI Video (legacy — runs through to publish)",
    "📄  Existing Script (legacy)",
    "🖼   Images Only",
    "🎙   Voice Only",
    "📝   Captions Only",
    "🎞   Render Existing Project",
    "📦  Publish Existing Project",
]

_STYLES = ["Documentary", "Spiritual", "Educational", "History", "No style"]
_STYLE_MAP: dict[str, Optional[str]] = {
    "Spiritual": "spiritual",
    "Documentary": "documentary",
    "Educational": "educational",
    "History": "history",
    "No style": None,
}

_LANGUAGES: dict[str, str] = {
    "English (US)": "en",
    "English (GB)": "en-GB",
    "Hindi": "hi",
    "Marathi": "mr",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Japanese": "ja",
    "Chinese (Mandarin)": "zh",
    "Portuguese (Brazil)": "pt",
    "Arabic": "ar",
    "Russian": "ru",
    "Korean": "ko",
    "Italian": "it",
}

_PROFILES = ["Cinematic", "Balanced", "Premium", "Draft"]
_PROFILE_MAP: dict[str, str] = {
    "Cinematic": "cinematic",
    "Balanced": "balanced",
    "Premium": "premium",
    "Draft": "draft",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _print_banner() -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]YouTube Factory[/bold cyan]\n"
            "[dim]Professional AI Video Production[/dim]",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()


def _load_settings_defaults() -> dict:
    try:
        from ytfactory.config.settings import Settings

        s = Settings()
        return {
            "image_provider": s.image_provider,
            "tts_provider": s.tts_provider,
            "render_profile": s.render_profile,
        }
    except Exception:
        return {
            "image_provider": "pollinations",
            "tts_provider": "edge",
            "render_profile": "cinematic",
        }


def _list_existing_projects() -> list[str]:
    jobs_dir = Path("workspace/jobs")
    if not jobs_dir.exists():
        return []
    return sorted(
        p.name
        for p in jobs_dir.iterdir()
        if p.is_dir() and (p / "project.json").exists()
    )


def _is_phase1_ready(project_dir: Path) -> bool:
    report = project_dir / "phase1_report.md"
    manifest = project_dir / "image_prompts_manifest.json"
    final = project_dir / "video" / "final.mp4"
    return report.exists() and manifest.exists() and not final.exists()


def _list_phase1_ready_projects() -> list[str]:
    jobs_dir = Path("workspace/jobs")
    if not jobs_dir.exists():
        return []
    return sorted(
        p.name
        for p in jobs_dir.iterdir()
        if p.is_dir() and (p / "project.json").exists() and _is_phase1_ready(p)
    )


def _ask_project_id(label: str = "Project ID") -> Optional[str]:
    existing = _list_existing_projects()
    if existing:
        choices = existing + ["— type a different ID —"]
        choice = questionary.select(f"{label}:", choices=choices).ask()
        if choice is None:
            return None
        if choice == "— type a different ID —":
            return questionary.text("Enter project ID:").ask() or None
        return choice
    answer = questionary.text(f"{label}:").ask()
    return answer or None


def _ask_style(default: str = "Documentary") -> Optional[str]:
    label = questionary.select("Style:", choices=_STYLES, default=default).ask()
    return _STYLE_MAP.get(label or "No style")


def _ask_language(default: str = "English (US)") -> tuple[str, str]:
    label = questionary.select(
        "Language:", choices=list(_LANGUAGES), default=default
    ).ask()
    lang_label = label or "English (US)"
    return lang_label, _LANGUAGES.get(lang_label, "en")


def _ask_ab_selection() -> bool:
    return bool(
        questionary.confirm(
            "Generate 2 script variants to choose from?",
            default=True,
            instruction="(runs the composer twice, then you pick the better one)",
        ).ask()
    )


def _ask_profile(default: str = "Cinematic") -> str:
    label = questionary.select(
        "Render profile:", choices=_PROFILES, default=default
    ).ask()
    return _PROFILE_MAP.get(label or "Cinematic", "cinematic")


def _ask_target_minutes() -> int:
    answer = questionary.text("Target duration in minutes (1–10):", default="5").ask()
    try:
        return max(1, min(10, int(answer or "5")))
    except ValueError:
        return 5


def _confirm_launch(params: dict) -> bool:
    console.print()
    lines = "\n".join(f"  [bold]{k}:[/bold] {v}" for k, v in params.items())
    console.print(
        Panel(
            lines,
            title="[cyan]Ready to produce[/cyan]",
            border_style="cyan",
            padding=(0, 2),
        )
    )
    console.print()
    result = questionary.confirm("Confirm and start?", default=True).ask()
    if result:
        console.print()
    return bool(result)


def _apply_profile_env(profile: str) -> None:
    """Override render profile for this run without touching .env."""
    os.environ["RENDER_PROFILE"] = profile


# ── Workflow flows ────────────────────────────────────────────────────────────


def _flow_new_project(defaults: dict) -> None:
    title = questionary.text("Video title:").ask()
    if not title:
        return

    from slugify import slugify

    project_dir = Path("workspace/jobs") / slugify(title)
    existing_images = sorted(project_dir.glob("images/scene-*.png")) if project_dir.exists() else []
    if existing_images:
        console.print(
            f"\n[bold yellow]⚠  Project '{slugify(title)}' already exists with {len(existing_images)} images.[/bold yellow]\n"
            f"  Re-running Phase 1 will overwrite the script and scene plan.\n"
            f"  Existing images will be out of sync until regenerated."
        )
        confirm_rerun = questionary.confirm(
            f"Proceed and overwrite? ({len(existing_images)} existing images will be out of sync)",
            default=False,
        ).ask()
        if not confirm_rerun:
            return

    source_choice = questionary.select(
        "Source:",
        choices=["Existing base script (file path)", "YouTube URL"],
    ).ask()
    if not source_choice:
        return

    script_path: str | None = None
    source_url: str | None = None

    if source_choice == "YouTube URL":
        source_url = questionary.text("YouTube URL:").ask()
        if not source_url:
            return
        source_url = source_url.strip()
    else:
        script_path = questionary.text(
            "Script file path:",
            instruction="(.md, .txt, .pdf, .docx)",
        ).ask()
        if not script_path:
            return
        script_path = script_path.strip()
        if not Path(script_path).exists():
            console.print(f"[red]File not found: {script_path}[/red]")
            return

    style = _ask_style()
    target_mins = _ask_target_minutes()
    lang_label, language = _ask_language()
    profile = _ask_profile()
    auto = questionary.confirm(
        "Run fully automatically (skip review gates)?", default=False
    ).ask()

    if not _confirm_launch(
        {
            "Title": title,
            "Script": script_path or "YouTube ingest",
            **({"YouTube URL": source_url} if source_url else {}),
            "Style": style or "none",
            "Duration": f"{target_mins} min  (~{target_mins * 130} words)",
            "Language": lang_label,
            "Profile": profile,
            "Script path": "Atma 7-Beat refinement",
            "Phase": "1 (prep)",
        }
    ):
        return

    _apply_profile_env(profile)
    from ytfactory.agents.runner import run_pipeline

    run_pipeline(
        title,
        language=language,
        auto=bool(auto),
        script_path=script_path,
        source_url=source_url,
        style=style,
        target_minutes=target_mins,
        pipeline_mode="prep_only",
        ab_script_selection=False,
    )


def _flow_full_ai_video(defaults: dict) -> None:
    title = questionary.text("Video title:").ask()
    if not title:
        return

    style = _ask_style()
    target_mins = _ask_target_minutes()
    lang_label, language = _ask_language()
    profile = _ask_profile()
    auto = questionary.confirm(
        "Run fully automatically (skip review gates)?", default=False
    ).ask()

    if not _confirm_launch(
        {
            "Title": title,
            "Style": style or "none",
            "Duration": f"{target_mins} min  (~{target_mins * 130} words)",
            "Language": lang_label,
            "Profile": profile,
            "Script path": "Atma 7-Beat refinement",
            "Images": defaults.get("image_provider", "?"),
            "TTS": defaults.get("tts_provider", "?"),
            "Mode": "fully automatic" if auto else "with review gates",
        }
    ):
        return

    _apply_profile_env(profile)
    from ytfactory.agents.runner import run_pipeline

    run_pipeline(
        title,
        language=language,
        auto=bool(auto),
        style=style,
        target_minutes=target_mins,
        ab_script_selection=False,
    )


def _flow_existing_script(defaults: dict) -> None:
    title = questionary.text("Video title:").ask()
    if not title:
        return

    script_path = questionary.text(
        "Script file path:",
        instruction="(.md, .txt, .pdf, .docx)",
    ).ask()
    if not script_path:
        return
    script_path = script_path.strip()
    if not Path(script_path).exists():
        console.print(f"[red]File not found: {script_path}[/red]")
        return

    style = _ask_style()
    target_mins = _ask_target_minutes()
    lang_label, language = _ask_language()
    profile = _ask_profile()
    auto = questionary.confirm(
        "Run fully automatically (skip review gates)?", default=False
    ).ask()

    if not _confirm_launch(
        {
            "Title": title,
            "Script": script_path,
            "Style": style or "none",
            "Duration": f"{target_mins} min (~{target_mins * 130} words)",
            "Language": lang_label,
            "Profile": profile,
            "Script path": "Atma 7-Beat refinement",
            "Images": defaults.get("image_provider", "?"),
            "TTS": defaults.get("tts_provider", "?"),
            "Mode": "fully automatic" if auto else "with review gates",
        }
    ):
        return

    _apply_profile_env(profile)
    from ytfactory.agents.runner import run_pipeline

    run_pipeline(
        title,
        script_path=script_path,
        language=language,
        auto=bool(auto),
        style=style,
        target_minutes=target_mins,
        ab_script_selection=False,
    )


def _flow_images_only() -> None:
    project_id = _ask_project_id("Project ID for image generation")
    if not project_id:
        return

    if not _confirm_launch({"Project": project_id, "Stage": "Image generation"}):
        return

    from ytfactory.config.settings import Settings
    from ytfactory.images.pipeline import ImagePipeline

    ImagePipeline(Settings()).run(project_id)


def _flow_voice_only() -> None:
    project_id = _ask_project_id("Project ID for voice generation")
    if not project_id:
        return

    style_label = questionary.select(
        "Style:", choices=_STYLES, default="Documentary"
    ).ask()
    style = _STYLE_MAP.get(style_label or "Documentary") or "documentary"

    if not _confirm_launch(
        {"Project": project_id, "Stage": "Voice generation", "Style": style}
    ):
        return

    from ytfactory.config.settings import Settings
    from ytfactory.voice.pipeline import VoicePipeline

    VoicePipeline(Settings()).run(project_id, style=style)


def _flow_captions_only() -> None:
    project_id = _ask_project_id("Project ID for caption generation")
    if not project_id:
        return

    if not _confirm_launch(
        {"Project": project_id, "Stage": "Caption generation"}
    ):
        return

    from ytfactory.captions.pipeline import CaptionPipeline

    CaptionPipeline().run(project_id)


def _flow_render() -> None:
    project_id = _ask_project_id("Project ID to render")
    if not project_id:
        return

    profile = _ask_profile()

    if not _confirm_launch(
        {"Project": project_id, "Stage": "Render", "Profile": profile}
    ):
        return

    _apply_profile_env(profile)
    from ytfactory.video.pipeline import VideoPipeline

    VideoPipeline().run(project_id)


def _flow_publish() -> None:
    project_id = _ask_project_id("Project ID to publish")
    if not project_id:
        return

    skip_thumbnail = questionary.confirm(
        "Skip thumbnail generation? (saves image API calls)",
        default=False,
    ).ask()

    if not _confirm_launch(
        {
            "Project": project_id,
            "Stage": "Publish",
            "Thumbnail": "skipped" if skip_thumbnail else "generate",
        }
    ):
        return

    from ytfactory.publish.pipeline import PublishConfig, PublishPipeline

    config = PublishConfig(skip_thumbnail=bool(skip_thumbnail))
    PublishPipeline(config=config).run(project_id)


def _flow_replan_scenes() -> None:
    project_id = _ask_project_id("Project ID to re-plan scenes for")
    if not project_id:
        return

    project_dir = Path("workspace/jobs") / project_id
    script_path = project_dir / "script" / "script.md"
    scene_plan_path = project_dir / "scenes" / "scene-plan.json"

    if not script_path.exists():
        console.print(f"[red]No script found at {script_path}[/red]")
        console.print("[dim]Run 'New Project (Phase 1)' first to generate a script.[/dim]")
        return

    # ── Sub-option: re-export prompts from cached plan (no LLM re-planning) ──
    if scene_plan_path.exists():
        action = questionary.select(
            "Scene plan exists. What would you like to do?",
            choices=[
                "Re-export image prompts from existing plan (re-applies latest prompt assembly rules, no LLM)",
                "Re-plan from scratch (full LLM scene planning)",
            ],
        ).ask()
        if action is None:
            return

        if "Re-export" in action:
            _flow_reexport_prompts(project_id, project_dir, scene_plan_path)
            return

    # ── Full re-plan path ─────────────────────────────────────────────────────
    existing_images = sorted((project_dir / "images").glob("scene-*.png")) if (project_dir / "images").exists() else []

    if existing_images:
        console.print(
            f"\n[bold yellow]⚠  {len(existing_images)} images already exist for this project.[/bold yellow]\n"
            f"  Re-planning will generate a new scene plan that no longer matches those images.\n"
            f"  You will need to regenerate all images afterwards."
        )
        confirm_images = questionary.confirm(
            f"Proceed anyway? ({len(existing_images)} existing images will be out of sync until regenerated)",
            default=False,
        ).ask()
        if not confirm_images:
            return

    if scene_plan_path.exists():
        scene_plan_path.unlink()
        console.print("[dim]Deleted scene-plan.json[/dim]")

    profile = _ask_profile()

    import json as _json
    title = _json.loads((project_dir / "project.json").read_text()).get("title", project_id)

    if not _confirm_launch({
        "Project": project_id,
        "Title": title,
        "Script": str(script_path),
        "Stage": "Phase 1 (scene planning → voice → captions → image prompts)",
        "Profile": profile,
    }):
        return

    _apply_profile_env(profile)
    from ytfactory.agents.runner import run_pipeline

    run_pipeline(
        title,
        project_id=project_id,
        auto=True,
        pipeline_mode="prep_only",
        ab_script_selection=False,
    )
    console.print(
        "\n[dim]Phase 1 complete. Generate images externally, place them in "
        f"workspace/jobs/{project_id}/images/, then run 'Resume Project (Phase 2)'.[/dim]"
    )


def _flow_reexport_prompts(project_id: str, project_dir: Path, scene_plan_path: Path) -> None:
    """Re-export IMAGE_PROMPTS.md from a cached scene-plan.json without re-running the LLM.

    Calls _write_prompts_file() which runs _assemble_export_prompt() on all cached scenes,
    applying the latest prompt assembly rules (typography, character classification, etc.).
    """
    import json as _json

    if not _confirm_launch({"Project": project_id, "Stage": "Re-export image prompts (no LLM)"}):
        return

    scene_plan = _json.loads(scene_plan_path.read_text(encoding="utf-8"))
    scenes = scene_plan.get("scenes", [])
    style = scene_plan.get("style")

    from ytfactory.agents.nodes.scene_planner import _write_prompts_file
    from ytfactory.config.settings import Settings

    settings = Settings()
    prompts_path = _write_prompts_file(project_id, scenes, style, settings)
    console.print(f"\n[green]✓[/green] Image prompts re-exported: [dim]{prompts_path}[/dim]")


def _flow_resume_project() -> None:
    existing = _list_phase1_ready_projects()
    if not existing:
        console.print("[yellow]No Phase 1-ready projects found.[/yellow]")
        console.print(
            "[dim]Projects must have phase1_report.md and image_prompts_manifest.json "
            "and must not yet have video/final.mp4.[/dim]"
        )
        return

    project_id = questionary.select(
        "Select a project to resume (Phase 2):",
        choices=existing,
    ).ask()
    if not project_id:
        return

    if not _confirm_launch(
        {
            "Project": project_id,
            "Phase": "2 (resume)",
        }
    ):
        return

    from ytfactory.build.pipeline import BuildPipeline

    overlay = questionary.confirm(
        "Apply motion overlay compositing?",
        default=False,
    ).ask()

    BuildPipeline().run_resume(project_id, overlay=overlay)


def _flow_resume() -> None:
    project_id = _ask_project_id("Project ID to resume")
    if not project_id:
        return

    title = questionary.text("Video title (for pipeline context):").ask()
    if not title:
        return

    auto = questionary.confirm("Run fully automatically?", default=False).ask()

    if not _confirm_launch(
        {
            "Project": project_id,
            "Title": title,
            "Mode": "fully automatic" if auto else "with review gates",
        }
    ):
        return

    from ytfactory.agents.runner import run_pipeline

    run_pipeline(title, project_id=project_id, auto=bool(auto))


# ── Shorts flows ─────────────────────────────────────────────────────────────


def _flow_shorts_phase1() -> None:
    """S1 → S2 → S2b → S3 → S4: extract opportunities, generate scripts, plan scenes."""
    project_id = _ask_project_id("Long-form project to generate Shorts from")
    if not project_id:
        return

    project_dir = Path("workspace/jobs") / project_id
    script_path = project_dir / "script" / "script.md"
    if not script_path.exists():
        console.print(f"[red]No script found at {script_path}[/red]")
        console.print("[dim]Run 'New Project (Phase 1)' first to generate a long-form script.[/dim]")
        return

    force = questionary.confirm(
        "Regenerate even if Shorts artifacts already exist?",
        default=False,
    ).ask()

    if not _confirm_launch(
        {
            "Project": project_id,
            "Stage": "Shorts Phase 1 (extract → scripts → scene plans)",
            "Force": "yes" if force else "no (skip existing)",
        }
    ):
        return

    from ytfactory.config.settings import Settings
    from ytfactory.shorts.pipeline import ShortsPipeline

    ShortsPipeline(Settings()).run(project_id, force=bool(force))

    console.print(
        "\n[dim]Phase 1 complete. Open each short's image-prompts.json, generate "
        "images externally, drop PNGs into "
        f"workspace/jobs/{project_id}/shorts/<short-id>/images/, "
        "then run 'Render Shorts Video (Phase 2)'.[/dim]"
    )


def _flow_shorts_phase2() -> None:
    """Images → TTS → subtitles → render → assemble → BGM → final.mp4."""
    project_id = _ask_project_id("Project ID whose Shorts videos to render")
    if not project_id:
        return

    shorts_base = Path("workspace/jobs") / project_id / "shorts"
    available_shorts: list[str] = []
    if shorts_base.exists():
        available_shorts = sorted(
            d.name for d in shorts_base.iterdir()
            if d.is_dir() and (d / "scene-plan.json").exists()
        )

    short_id: str | None = None
    if available_shorts:
        choices = ["All Shorts"] + available_shorts
        pick = questionary.select(
            "Which Short to render?",
            choices=choices,
            default="All Shorts",
        ).ask()
        if pick is None:
            return
        short_id = None if pick == "All Shorts" else pick
    else:
        console.print(
            f"[yellow]No scene plans found under {shorts_base}.[/yellow]\n"
            "[dim]Run 'Generate Shorts (Phase 1)' first.[/dim]"
        )
        return

    if short_id:
        images_dir = shorts_base / short_id / "images"
        images = list(images_dir.glob("scene-*.png")) if images_dir.exists() else []
        if not images:
            console.print(
                f"\n[bold yellow]⚠  No images found in {images_dir}[/bold yellow]\n"
                f"  Drop scene-001.png, scene-002.png … into that folder first,\n"
                f"  then re-run this step."
            )
    else:
        console.print(
            "\n[dim]Tip: drop scene-NNN.png files into each "
            f"workspace/jobs/{project_id}/shorts/<short-id>/images/ folder before continuing.[/dim]"
        )

    force = questionary.confirm(
        "Regenerate all media stages even if outputs already exist?",
        default=False,
    ).ask()

    if not _confirm_launch(
        {
            "Project": project_id,
            "Short": short_id or "all",
            "Stage": "Shorts Phase 2 (TTS → subtitles → render → BGM)",
            "Force": "yes" if force else "no (skip existing)",
        }
    ):
        return

    from ytfactory.config.settings import Settings
    from ytfactory.shorts.media_pipeline import ShortsMediaPipeline

    ShortsMediaPipeline(Settings()).run_all(
        project_id,
        short_id_filter=short_id,
        force=bool(force),
    )


# ── Entry point ───────────────────────────────────────────────────────────────


def run_wizard() -> None:
    _print_banner()
    defaults = _load_settings_defaults()

    try:
        preset = questionary.select(
            "What would you like to do?",
            choices=_PRESETS,
        ).ask()
    except KeyboardInterrupt:
        console.print("\n[yellow]Wizard cancelled.[/yellow]")
        return

    if preset is None:
        console.print("\n[yellow]Wizard cancelled.[/yellow]")
        return

    console.print()

    try:
        if "New Project" in preset:
            _flow_new_project(defaults)
        elif "Re-plan Scenes" in preset:
            _flow_replan_scenes()
        elif "Resume Project" in preset:
            _flow_resume_project()
        elif "Generate Shorts" in preset:
            _flow_shorts_phase1()
        elif "Render Shorts" in preset:
            _flow_shorts_phase2()
        elif "Full AI Video" in preset:
            _flow_full_ai_video(defaults)
        elif "Existing Script" in preset:
            _flow_existing_script(defaults)
        elif "Images Only" in preset:
            _flow_images_only()
        elif "Voice Only" in preset:
            _flow_voice_only()
        elif "Captions Only" in preset:
            _flow_captions_only()
        elif "Render Existing" in preset:
            _flow_render()
        elif "Publish" in preset:
            _flow_publish()
        elif "Resume" in preset:
            _flow_resume()
    except KeyboardInterrupt:
        console.print("\n[yellow]Wizard cancelled.[/yellow]")
