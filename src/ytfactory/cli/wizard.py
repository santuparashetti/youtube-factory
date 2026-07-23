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
    "🎬  Full AI Video (research → script → video)",
    "📄  Existing Script (skip research, use my script)",
    "🔍  Research Only",
    "🖼   Images Only",
    "🎙   Voice Only",
    "🎞   Render Existing Project",
    "📦  Publish Existing Project",
    "▶   Resume Existing Project",
]

_STYLES = ["Spiritual", "Documentary", "Educational", "History", "No style"]
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


def _ask_style(default: str = "Spiritual") -> Optional[str]:
    label = questionary.select("Style:", choices=_STYLES, default=default).ask()
    return _STYLE_MAP.get(label or "No style")


def _ask_language(default: str = "English (US)") -> tuple[str, str]:
    label = questionary.select(
        "Language:", choices=list(_LANGUAGES), default=default
    ).ask()
    lang_label = label or "English (US)"
    return lang_label, _LANGUAGES.get(lang_label, "en")


def _ask_profile(default: str = "Cinematic") -> str:
    label = questionary.select(
        "Render profile:", choices=_PROFILES, default=default
    ).ask()
    return _PROFILE_MAP.get(label or "Cinematic", "cinematic")


def _ask_target_minutes() -> int:
    answer = questionary.text("Target duration in minutes (1–10):", default="8").ask()
    try:
        return max(1, min(10, int(answer or "8")))
    except ValueError:
        return 8


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


def _flow_full_ai_video(defaults: dict) -> None:
    title = questionary.text("Video title:").ask()
    if not title:
        return

    style = _ask_style()
    target_mins = _ask_target_minutes()
    lang_label, language = _ask_language()
    profile = _ask_profile()
    auto = questionary.confirm(
        "Run fully automatically (skip review gates)?", default=True
    ).ask()

    if not _confirm_launch(
        {
            "Title": title,
            "Style": style or "none",
            "Duration": f"{target_mins} min  (~{target_mins * 130} words)",
            "Language": lang_label,
            "Profile": profile,
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
        "Run fully automatically (skip review gates)?", default=True
    ).ask()

    if not _confirm_launch(
        {
            "Title": title,
            "Script": script_path,
            "Style": style or "none",
            "Duration": f"{target_mins} min (~{target_mins * 130} words)",
            "Language": lang_label,
            "Profile": profile,
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
    )


def _flow_research_only() -> None:
    title = questionary.text("Video title (a new project will be created):").ask()
    if not title:
        return

    if not _confirm_launch({"Title": title, "Stage": "Research only"}):
        return

    from ytfactory.create.pipeline import CreatePipeline
    from ytfactory.research.pipeline import ResearchPipeline

    project = CreatePipeline().run(title)
    console.print(f"[green]✓[/green] Project created: [bold]{project.id}[/bold]")
    ResearchPipeline().run(project.id)
    console.print(
        f"\n[green]✓[/green] Research complete\n"
        f"  [dim]workspace/jobs/{project.id}/research/research.md[/dim]"
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
        "Style:", choices=_STYLES, default="Spiritual"
    ).ask()
    style = _STYLE_MAP.get(style_label or "Spiritual") or "spiritual"

    if not _confirm_launch(
        {"Project": project_id, "Stage": "Voice generation", "Style": style}
    ):
        return

    from ytfactory.config.settings import Settings
    from ytfactory.voice.pipeline import VoicePipeline

    VoicePipeline(Settings()).run(project_id, style=style)


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


def _flow_resume() -> None:
    project_id = _ask_project_id("Project ID to resume")
    if not project_id:
        return

    title = questionary.text("Video title (for pipeline context):").ask()
    if not title:
        return

    auto = questionary.confirm("Run fully automatically?", default=True).ask()

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
        if "Full AI Video" in preset:
            _flow_full_ai_video(defaults)
        elif "Existing Script" in preset:
            _flow_existing_script(defaults)
        elif "Research Only" in preset:
            _flow_research_only()
        elif "Images Only" in preset:
            _flow_images_only()
        elif "Voice Only" in preset:
            _flow_voice_only()
        elif "Render Existing" in preset:
            _flow_render()
        elif "Publish" in preset:
            _flow_publish()
        elif "Resume" in preset:
            _flow_resume()
    except KeyboardInterrupt:
        console.print("\n[yellow]Wizard cancelled.[/yellow]")
