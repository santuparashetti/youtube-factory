import os
import sys
from pathlib import Path
from typing import Optional

import typer
from loguru import logger
from rich.console import Console

from ytfactory.animate.cli import animate_scenes
from ytfactory.benchmark.cli import benchmark_app
from ytfactory.build.cli import build
from ytfactory.captions.cli import generate_captions, transcript
from ytfactory.cta.cli import overlay_cta
from ytfactory.create.cli import create
from ytfactory.doctor.cli import doctor
from ytfactory.editorial_qa.cli import editorial_qa, qa_app
from ytfactory.images.cli import generate_images
from ytfactory.import_script.cli import import_script
from ytfactory.light_normalization.cli import normalize
from ytfactory.research.cli import research
from ytfactory.review.cli import review
from ytfactory.publish.cli import publish
from ytfactory.review.remediation.cli import remediate
from ytfactory.scene.cli import scene_app
from ytfactory.scenes.cli import plan_scenes
from ytfactory.structural_retention.cli import structural_retention
from ytfactory.composer.cli import compose
from ytfactory.source_refiner.cli import refine_source
from ytfactory.trim.cli import trim_script
from ytfactory.video.cli import compare_video, render, stitch
from ytfactory.voice.cli import generate_voice
from ytfactory.shorts.cli import generate_shorts, generate_shorts_video, shorts_extract, shorts_plan

_console = Console()

app = typer.Typer(
    help="YouTube Factory CLI",
    no_args_is_help=False,  # wizard launches instead of help when no args given
)

app.command(name="doctor")(doctor)


@app.command(name="setup")
def setup(
    force: bool = typer.Option(
        False, "--force", help="Re-run even if already bootstrapped"
    ),
) -> None:
    """First-run bootstrap: workspace, config, providers, models. Idempotent."""
    from ytfactory.bootstrap.engine import BootstrapEngine
    from ytfactory.bootstrap.models import CheckStatus
    from rich.table import Table

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Setup[/bold]\n")
    result = engine.setup(force=force)

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", width=8)
    table.add_column("Check", min_width=30)
    table.add_column("Message")

    _STATUS = {
        CheckStatus.OK: "[green]✓[/green]",
        CheckStatus.WARNING: "[yellow]⚠[/yellow]",
        CheckStatus.ERROR: "[red]✗[/red]",
        CheckStatus.REPAIRED: "[cyan]↻[/cyan]",
        CheckStatus.SKIPPED: "[dim]−[/dim]",
    }
    for check in result.checks:
        table.add_row(_STATUS.get(check.status, "?"), check.name, check.message)
    _console.print(table)

    if result.repairs:
        _console.print(f"\n[cyan]Auto-repaired {len(result.repairs)} issue(s):[/cyan]")
        for r in result.repairs:
            _console.print(f"  ↻ {r}")

    if result.errors:
        _console.print(
            f"\n[red]✗ Setup completed with {len(result.errors)} error(s)[/red]"
        )
        for e in result.errors:
            _console.print(f"  ✗ {e.name}: {e.message}")
            if e.detail:
                _console.print(f"    {e.detail}")
        raise typer.Exit(1)
    elif result.warnings:
        _console.print(
            f"\n[yellow]⚠ Setup complete — {len(result.warnings)} warning(s)[/yellow]"
        )
    else:
        _console.print("\n[green]✓ Setup complete — environment ready[/green]")


@app.command(name="validate")
def validate() -> None:
    """Validate configuration and provider connectivity (lightweight, no setup)."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Validate[/bold]\n")
    result = engine.validate()

    for check in result.checks:
        icon = {
            "ok": "✓",
            "warning": "⚠",
            "error": "✗",
            "repaired": "↻",
            "skipped": "−",
        }.get(check.status.value, "?")
        color = {
            "ok": "green",
            "warning": "yellow",
            "error": "red",
            "repaired": "cyan",
            "skipped": "dim",
        }.get(check.status.value, "white")
        _console.print(f"  [{color}]{icon}[/{color}] {check.name}: {check.message}")
        if check.detail:
            _console.print(f"    [dim]{check.detail}[/dim]")

    if result.errors:
        _console.print(f"\n[red]✗ {len(result.errors)} validation error(s)[/red]")
        raise typer.Exit(1)
    elif result.warnings:
        _console.print(f"\n[yellow]⚠ {len(result.warnings)} warning(s)[/yellow]")
    else:
        _console.print("\n[green]✓ Configuration valid[/green]")


@app.command(name="repair")
def repair() -> None:
    """Self-healing: fix missing directories, permissions, broken symlinks."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Repair[/bold]\n")
    result = engine.repair()

    if not result.repairs and not result.errors:
        _console.print("[green]✓ Nothing to repair — environment is healthy[/green]")
        return

    for check in result.checks:
        if check.repaired:
            _console.print(f"  [cyan]↻ {check.message}[/cyan]")
        elif check.status.value == "error":
            _console.print(f"  [red]✗ {check.name}: {check.message}[/red]")
            if check.detail:
                _console.print(f"    {check.detail}")

    if result.repairs:
        _console.print(f"\n[cyan]Repaired {len(result.repairs)} issue(s)[/cyan]")
    if result.errors:
        _console.print(
            f"\n[red]✗ {len(result.errors)} issue(s) could not be auto-repaired — manual intervention needed[/red]"
        )
        raise typer.Exit(1)


@app.command(name="clean")
def clean(
    temp: bool = typer.Option(True, "--temp/--no-temp", help="Clean temp/ directory"),
    logs: bool = typer.Option(False, "--logs", help="Also clean logs/ directory"),
    cache: bool = typer.Option(
        False, "--cache", help="Also clean cache/ directory (keeps models)"
    ),
) -> None:
    """Clean temporary files. Safe — never touches workspace/jobs or models."""
    import shutil
    from pathlib import Path

    root = Path.cwd()
    cleaned: list[str] = []

    def _clean_dir(rel: str) -> None:
        target = root / rel
        if target.exists():
            shutil.rmtree(target)
            target.mkdir(parents=True, exist_ok=True)
            cleaned.append(rel)

    _console.print("\n[bold]YouTube Factory — Clean[/bold]\n")

    if temp:
        _clean_dir("temp")
    if logs:
        _clean_dir("logs")
    if cache:
        _clean_dir("cache")

    if cleaned:
        _console.print(f"[green]✓ Cleaned: {', '.join(cleaned)}[/green]")
    else:
        _console.print("[dim]Nothing to clean (use --logs or --cache for more)[/dim]")


@app.command(name="reset")
def reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    workspace: bool = typer.Option(
        False, "--workspace", help="Also delete workspace/jobs (DESTRUCTIVE)"
    ),
) -> None:
    """Reset bootstrap state. Re-run 'ytfactory setup' after this."""
    import shutil
    from pathlib import Path

    root = Path.cwd()

    if not yes:
        msg = "This will delete bootstrap-manifest.json and environment-report.json."
        if workspace:
            msg += " [red]Also deletes workspace/jobs/ — all project data will be lost![/red]"
        _console.print(f"\n[yellow]{msg}[/yellow]")
        confirm = typer.confirm("Continue?", default=False)
        if not confirm:
            _console.print("Reset cancelled.")
            raise typer.Exit(0)

    removed: list[str] = []
    for fname in ["bootstrap-manifest.json", "environment-report.json"]:
        p = root / fname
        if p.exists():
            p.unlink()
            removed.append(fname)

    if workspace:
        jobs = root / "workspace" / "jobs"
        if jobs.exists():
            shutil.rmtree(jobs)
            jobs.mkdir(parents=True, exist_ok=True)
            removed.append("workspace/jobs/")

    if removed:
        _console.print(f"[yellow]Removed: {', '.join(removed)}[/yellow]")
        _console.print("Run [bold]ytfactory setup[/bold] to re-bootstrap.")
    else:
        _console.print("[dim]Nothing to reset.[/dim]")


@app.command(name="update")
def update() -> None:
    """Re-validate environment after code/dependency updates."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    _console.print("\n[bold]YouTube Factory — Update[/bold]\n")

    result = engine.setup(force=True)

    if result.success:
        _console.print("[green]✓ Environment re-validated and manifest updated[/green]")
    else:
        _console.print(
            f"[red]✗ Re-validation found {len(result.errors)} error(s)[/red]"
        )
        raise typer.Exit(1)


@app.command(name="version")
def version() -> None:
    """Print version info and bootstrap manifest."""
    from ytfactory.bootstrap.engine import BootstrapEngine

    engine = BootstrapEngine()
    info = engine.version_info()

    current = info["current"]
    manifest = info["manifest"]

    _console.print(
        f"\n[bold]YouTube Factory[/bold]  v{current.get('project_version', '?')}"
    )
    _console.print(f"  Python:   {current.get('python_version', '?')}")
    _console.print(f"  FFmpeg:   {current.get('ffmpeg_version', '?')[:60]}")
    _console.print(f"  Torch:    {current.get('torch_version', '?')}")
    providers = current.get("providers", {})
    if providers:
        _console.print(f"  LLM:      {providers.get('llm', '?')}")
        _console.print(f"  Search:   {providers.get('search', '?')}")
        _console.print(f"  Image:    {providers.get('image', '?')}")
        _console.print(f"  TTS:      {providers.get('tts', '?')}")

    if manifest:
        _console.print(
            f"\n  Bootstrap: v{manifest.get('bootstrap_version', '?')} "
            f"({'current' if info['manifest_current'] else 'outdated'})"
        )
        _console.print(
            f"  Validated: {manifest.get('validated_at', '?')[:19].replace('T', ' ')}"
        )
    else:
        _console.print("\n  [dim]No bootstrap manifest — run 'ytfactory setup'[/dim]")


app.command(name="create")(create)
app.command(name="research")(research)
app.command(name="import-script")(import_script)
app.command(name="refine-source")(refine_source)
app.command(name="normalize")(normalize)
app.command(name="compose")(compose)
app.command(name="trim-script")(trim_script)
app.command(name="structural-retention")(structural_retention)
app.command(name="editorial-qa")(editorial_qa)
app.command(name="plan-scenes")(plan_scenes)
app.command(name="generate-images")(generate_images)
app.command(name="animate-scenes")(animate_scenes)
app.command(name="generate-voice")(generate_voice)
app.command(name="generate-captions")(generate_captions)
app.command(name="transcript")(transcript)
app.command(name="render")(render)
app.command(name="stitch")(stitch)
app.command(name="compare-video")(compare_video)
app.command(name="overlay-cta")(overlay_cta)
app.command(name="review")(review)
app.command(name="remediate")(remediate)
app.command(name="publish")(publish)
app.command(name="build")(build)
app.command(name="generate-shorts")(generate_shorts)
app.command(name="generate-shorts-video")(generate_shorts_video)
app.command(name="shorts-extract")(shorts_extract)
app.command(name="shorts-plan")(shorts_plan)
app.add_typer(scene_app, name="scene")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(qa_app, name="qa-promotions")


@app.command(name="mix-bgm")
def mix_bgm(
    project_id: str = typer.Argument(..., help="Project ID to apply BGM to"),
    video: Optional[str] = typer.Option(
        None, "--video", "-v", help="Path to video file (default: video/final.mp4)"
    ),
) -> None:
    """Re-apply background music to an already-rendered final.mp4.

    This is the standalone BGM re-apply path. BGM is normally embedded
    automatically during `ytfactory render` / `ytfactory build` via the
    video pipeline. Use this command only when BGM was disabled during the
    original render, or after adding new tracks to the BGM library.
    """
    from pathlib import Path
    from ytfactory.bgm.pipeline import BGMPipeline

    pipeline = BGMPipeline()
    video_path = Path(video) if video else None
    result = pipeline.run(project_id, video_path=video_path)
    if result is None:
        _console.print("[yellow]BGM skipped (disabled or no matching tracks).[/yellow]")


@app.command(name="export-scene-manifest")
def export_scene_manifest(
    project_id: str = typer.Argument(..., help="Project ID to export manifest for"),
) -> None:
    """Export a generic per-scene manifest for downstream factories (e.g. shorts_factory).

    Writes workspace/jobs/<project-id>/publish/scene-manifest.json with
    absolute image_path, audio_path, narration_text, and duration_seconds
    per scene.  Does not require publish to have run first.
    """
    from ytfactory.publish.generators.scene_manifest import SceneManifestGenerator

    entries = SceneManifestGenerator().generate(project_id)
    _console.print(
        f"[green]Wrote {len(entries)} scene(s) → publish/scene-manifest.json[/green]"
    )


@app.command(name="export-image-prompts")
def export_image_prompts_cmd(
    project_id: str = typer.Argument(..., help="Project ID"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output directory (default: workspace/jobs/<id>/publish/)"),
    chunk: int = typer.Option(9, "--chunk", "-n", help="Scenes per output file (default: 9)"),
) -> None:
    """Export per-scene image prompts as chunked markdown files for manual image generation.

    Reads scene-plan.json and writes one markdown file per chunk of scenes to
    workspace/jobs/<project-id>/publish/ (or --output). Each file contains the
    ChatGPT/DALL-E setup preamble, global style instructions, and fully formatted
    per-scene prompts with CHARACTER PRESENCE labels.
    """
    from ytfactory.images.export import export_image_prompts

    out_dir = Path(output) if output else None
    try:
        written = export_image_prompts(project_id, output_dir=out_dir, chunk_size=chunk)
    except FileNotFoundError as exc:
        _console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    for path in written:
        _console.print(f"[green]✓[/green] {path}")
    _console.print(f"[bold]{len(written)} file(s) written.[/bold]")


@app.command(name="verify-images")
def verify_images_cmd(
    project: str = typer.Option(..., "--project", help="Project ID"),
    scenes: str = typer.Option(None, "--scenes", help="Comma-separated scene IDs to verify"),
    auto: bool = typer.Option(False, "--auto", help="Non-interactive mode"),
) -> None:
    """Phase 1.5: verify placed images against their visual prompts before Phase 2."""
    from ytfactory.config.settings import Settings
    from ytfactory.images.verify import verify_all_scenes, write_qa_report
    from ytfactory.shared.constants import WORKSPACE_DIR
    from video_core.providers.vision.factory import get_vision_provider

    settings = Settings()
    workspace = Path(WORKSPACE_DIR) / project
    manifest_path = workspace / "image_prompts_manifest.json"
    images_dir = workspace / "images"
    report_path = images_dir / "image_qa_report.json"

    if not manifest_path.is_file():
        typer.echo("No manifest found. Run Phase 1 first.")
        raise typer.Exit(1)

    if not settings.image_qa_enabled:
        typer.echo("IMAGE_QA_ENABLED=false — skipping verification.")
        return

    scene_filter = None
    if scenes:
        scene_filter = [int(s.strip()) for s in scenes.split(",")]

    vision_provider = get_vision_provider(
        settings.vision_review_provider, local_model=settings.vision_review_local_model
    )

    typer.echo(f"\n🔍 Verifying images for: {project}\n")
    results = verify_all_scenes(manifest_path, images_dir, vision_provider, scene_filter)

    report = write_qa_report(results, report_path)
    summary = report["summary"]

    typer.echo(f"\n{'─' * 60}")
    typer.echo(f"  KEEP:        {summary['keep']}/{summary['total']}")
    typer.echo(f"  REGENERATE:  {summary['regenerate']}/{summary['total']}")
    typer.echo(f"  MISSING:     {summary['missing']}/{summary['total']}")
    typer.echo(f"  Report:      {report_path}")
    typer.echo(f"{'─' * 60}\n")

    if summary["regenerate"] > 0:
        typer.echo("⚠  Some images need regeneration. See report for reasons.")
    if summary["missing"] > 0:
        typer.echo("⚠  Some images are missing. Place them before running Phase 2.")

    if summary["regenerate"] > 0 or summary["missing"] > 0:
        raise typer.Exit(1)


_KAI_MARKERS = ["dark hair", "simple dark shirt", "lean young man", "light stubble"]


@app.command(name="probe")
def probe(
    project_dir: str = typer.Argument(
        ..., help="Phase 1 output directory containing scene-plan.json"
    ),
) -> None:
    """Inspect a Phase 1 scene-plan.json and verify anchor_role classification.

    Reports the anchor_role distribution, runs a set of PASS/FAIL checks
    (every scene classified, opening not 'absent', closing 'primary', Kai spec
    markers present/absent per role, no 'Kai' name leaked into any prompt), and
    prints one sample prompt per role. Exits 1 if any check fails.
    """
    import json
    import re

    base = Path(project_dir)
    # Spec layout is <project-dir>/scene-plan.json; the repo writes it under
    # <project-dir>/scenes/scene-plan.json — accept either.
    candidates = [base / "scene-plan.json", base / "scenes" / "scene-plan.json"]
    plan_path = next((p for p in candidates if p.is_file()), None)
    if plan_path is None:
        _console.print(
            f"[red]✗ scene-plan.json not found[/red] — looked in:\n"
            f"    {candidates[0]}\n    {candidates[1]}"
        )
        raise typer.Exit(1)

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _console.print(f"[red]✗ Could not read {plan_path}: {exc}[/red]")
        raise typer.Exit(1)

    scenes = plan.get("scenes", [])
    total = len(scenes)

    kai_pattern = re.compile(r"\bkai\b", re.IGNORECASE)

    def _role(scene: dict) -> str | None:
        r = scene.get("anchor_role")
        return r if r in ("primary", "spectator", "absent") else None

    def _is_brand_or_asset(scene: dict) -> bool:
        return scene.get("scene_type") in ("asset", "brand_card")

    counts = {"primary": 0, "spectator": 0, "absent": 0, "MISSING": 0}
    for s in scenes:
        r = _role(s)
        counts["MISSING" if r is None else r] += 1

    def _pct(n: int) -> str:
        return f"{(100.0 * n / total):.0f}" if total else "0"

    # ── Checks ────────────────────────────────────────────────────────────
    all_classified = counts["MISSING"] == 0

    opening_role = _role(scenes[0]) if scenes else None
    opening_ok = bool(scenes) and opening_role is not None and opening_role != "absent"

    # Closing = last non-absent, non-brand/asset scene; fall back to 2nd-to-last.
    closing_scene = None
    for s in reversed(scenes):
        if not _is_brand_or_asset(s) and _role(s) not in (None, "absent"):
            closing_scene = s
            break
    if closing_scene is None and len(scenes) >= 2:
        closing_scene = scenes[-2]
    closing_role = _role(closing_scene) if closing_scene else None
    closing_ok = closing_role == "primary"

    primary_markers_ok = True
    for s in scenes:
        if _role(s) == "primary":
            vp = (s.get("visual_prompt") or "").lower()
            if not any(m in vp for m in _KAI_MARKERS):
                primary_markers_ok = False
                break

    absent_clean_ok = True
    for s in scenes:
        if _role(s) == "absent":
            vp = (s.get("visual_prompt") or "").lower()
            if any(m in vp for m in _KAI_MARKERS):
                absent_clean_ok = False
                break

    kai_prompt_count = sum(
        1 for s in scenes if kai_pattern.search(s.get("visual_prompt") or "")
    )

    # ── Scene group checks ────────────────────────────────────────────────
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in scenes:
        gid = s.get("scene_group_id")
        if gid:
            groups[gid].append(s)

    grouped_count = sum(len(v) for v in groups.values())

    continuity_ok = True
    for gid, group_scenes in groups.items():
        first = group_scenes[0]
        first_id = first.get("index", "?")
        for subsequent in group_scenes[1:]:
            vp = subsequent.get("visual_prompt") or ""
            if not vp.startswith(f"Continuous from scene {first_id}"):
                continuity_ok = False

    anchor_match_ok = True
    for gid, group_scenes in groups.items():
        first_anchor = group_scenes[0].get("environment_anchor") or ""
        for s in group_scenes[1:]:
            if (s.get("environment_anchor") or "") != first_anchor:
                anchor_match_ok = False

    footer_ok = all(
        "photorealistic" in (s.get("visual_prompt") or "").lower()
        for s in scenes
    )

    checks_pass = (
        all_classified
        and opening_ok
        and closing_ok
        and primary_markers_ok
        and absent_clean_ok
        and continuity_ok
        and anchor_match_ok
        and footer_ok
    )

    # ── Report ────────────────────────────────────────────────────────────
    def _mark(ok: bool) -> str:
        return "[green]✔[/green]" if ok else "[red]✗[/red]"

    _console.print(f"\n── [bold]Scene Plan Probe[/bold]: {project_dir} ──\n")
    _console.print(f"Scenes : {total}\n")
    _console.print("anchor_role distribution:")
    _console.print(f"  primary   : {counts['primary']}  ({_pct(counts['primary'])}%)")
    _console.print(f"  spectator : {counts['spectator']}  ({_pct(counts['spectator'])}%)")
    _console.print(f"  absent    : {counts['absent']}  ({_pct(counts['absent'])}%)")
    missing_suffix = "  [red]← FAIL[/red]" if counts["MISSING"] > 0 else ""
    _console.print(f"  MISSING   : {counts['MISSING']}{missing_suffix}\n")

    _console.print("scene_group distribution:")
    _console.print(f"  grouped scenes : {grouped_count}  (in {len(groups)} group{'s' if len(groups) != 1 else ''})")
    _console.print(f"  ungrouped      : {total - grouped_count}")
    if groups:
        _console.print("\nGroups:")
        for gid, group_scenes in sorted(groups.items()):
            ids = ", ".join(str(s.get("index", "?")) for s in group_scenes)
            anchor_snippet = (group_scenes[0].get("environment_anchor") or "")[:60]
            _console.print(f"  {gid} → scenes {ids}   [dim][environment_anchor: {anchor_snippet}...][/dim]")
    _console.print("")

    _console.print("Checks:")
    _console.print(f"  {_mark(all_classified)}  All scenes have anchor_role field")
    _console.print(
        f"  {_mark(opening_ok)}  Opening scene is not 'absent'   → actual: {opening_role or 'MISSING'}"
    )
    _console.print(
        f"  {_mark(closing_ok)}  Closing scene is 'primary'      → actual: {closing_role or 'MISSING'}"
    )
    _console.print(f"  {_mark(primary_markers_ok)}  All primary prompts contain Kai spec markers")
    _console.print(f"  {_mark(absent_clean_ok)}  All absent prompts are Kai-free")
    _console.print(f"  [dim]ℹ[/dim]  Kai name used in image prompts → {kai_prompt_count} of {total} prompts reference 'Kai'")
    _console.print("\nContinuity checks:")
    _console.print(f"  {_mark(continuity_ok)}  All grouped scenes (non-first) open with 'Continuous from scene X'")
    _console.print(f"  {_mark(anchor_match_ok)}  All grouped scenes have matching environment_anchor values within group")
    _console.print(f"  {_mark(footer_ok)}  All visual_prompts end with quality footer ('photorealistic' present)")

    # ── Samples ───────────────────────────────────────────────────────────
    def _first_with_role(role: str) -> dict | None:
        return next((s for s in scenes if _role(s) == role), None)

    _console.print("\n── [bold]Samples[/bold] ──")
    for role_label, role in (("PRIMARY", "primary"), ("SPECTATOR", "spectator"), ("ABSENT", "absent")):
        sample = _first_with_role(role)
        if sample is None:
            continue  # omit section when no scene has this role
        sid = sample.get("index", "?")
        snippet = (sample.get("visual_prompt") or "")[:250]
        _console.print(f"\n{role_label}  (scene {sid}):")
        _console.print(f"  [dim]{snippet}[/dim]")

    result = "PASS" if checks_pass else "FAIL"
    color = "green" if checks_pass else "red"
    _console.print(f"\n── [bold]Result: [{color}]{result}[/{color}][/bold] ──\n")

    if not checks_pass:
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """YouTube Factory — run without arguments to open the interactive wizard."""
    _configure_logging()
    if ctx.invoked_subcommand is None:
        from ytfactory.cli.wizard import run_wizard

        run_wizard()


def _configure_logging() -> None:
    """Reconfigure loguru from LOG_LEVEL env var (default: INFO).

    Replaces the loguru default sink so that level is driven by .env rather
    than loguru's built-in DEBUG default.  Called once at CLI startup before
    any pipeline code runs.
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
    )


@app.command(name="run")
def run(
    topic: str = typer.Argument(..., help="Video topic or title"),
    project_id: Optional[str] = typer.Option(
        None, "--project", "-p", help="Resume an existing project by ID"
    ),
    language: str = typer.Option(
        "en", "--language", "-l", help="BCP-47 language code for TTS"
    ),
    auto: bool = typer.Option(
        False, "--auto", help="Skip human-review gates (fully autonomous)"
    ),
    script: Optional[str] = typer.Option(
        None,
        "--script",
        "-s",
        help="Path to a pre-written script file. Skips research and script-writer stages.",
    ),
    youtube_url: Optional[str] = typer.Option(
        None,
        "--youtube-url",
        help="YouTube URL as the source instead of --script or AI research. Runs "
        "acquire-audio -> transcribe -> translate -> review before script_enhancer. "
        "Mutually exclusive with --script.",
    ),
    style: Optional[str] = typer.Option(
        None,
        "--style",
        help="Visual style: spiritual | documentary | educational | history (affects image prompts)",
    ),
    no_images: bool = typer.Option(
        False,
        "--no-images",
        help="Skip image generation. Review IMAGE_PROMPTS.md, generate images manually, then re-run.",
    ),
    target_minutes: int = typer.Option(
        7,
        "--target-minutes",
        "-t",
        help="Target narration duration in minutes (1-10). Drives script enhancer word count.",
    ),
    # ── Incremental / resume flags ────────────────────────────────────────────
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Skip stages whose outputs are unchanged (incremental mode)",
    ),
    reuse_assets: bool = typer.Option(
        False, "--reuse-assets", help="Alias for --resume"
    ),
    force_images: bool = typer.Option(
        False, "--force-images", help="Force image regeneration"
    ),
    force_narration: bool = typer.Option(
        False, "--force-narration", help="Force voice regeneration"
    ),
    force_subtitles: bool = typer.Option(
        False, "--force-subtitles", help="Force caption regeneration"
    ),
    force_motion: bool = typer.Option(
        False, "--force-motion", help="Force motion/video regeneration"
    ),
    force_video: bool = typer.Option(False, "--force-video", help="Force video render"),
    force_bgm: bool = typer.Option(
        False, "--force-bgm", help="Force BGM re-mix (implies --force-video)"
    ),
    force_publish: bool = typer.Option(
        False, "--force-publish", help="Force publish package regeneration"
    ),
    scene: Optional[int] = typer.Option(
        None, "--scene", help="Only process this scene index"
    ),
    force_scene: Optional[int] = typer.Option(
        None,
        "--force-scene",
        help="Force-regenerate one specific scene (overrides locked state)",
    ),
    phase: Optional[str] = typer.Option(
        None,
        "--phase",
        help="Two-phase mode: prep_only (Phase 1) or resume (Phase 2)",
    ),
    refiner_mode: str = typer.Option(
        "full",
        "--refiner-mode",
        help=(
            "Atma Refiner mode: 'full' (default — full 7-Beat editorial pass), "
            "'format' (markers + word-count only; preserves externally-reviewed scripts), "
            "or 'passthrough' (use base script exactly as-is — no edits, just validate)."
        ),
    ),
):
    """Run the full agentic video production pipeline.

    Research → Script → Scenes → Images + Voice (parallel) → Video → final.mp4

    Pass --script to skip research and use your own script directly.
    Pass --youtube-url to ingest a source video instead (audio -> transcript ->
    translated base script -> review), skipping research and --script both.
    Pass --no-images to skip image generation; place images manually then re-run.
    Pass --resume with --project for incremental builds — only changed stages re-run.

    \b
    INCREMENTAL MODE (requires --project)
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    --resume             Skip unchanged stages (SHA-256 checksum detection).
    --reuse-assets       Alias for --resume.
    --force-images       Force image regeneration + all downstream stages.
    --force-narration    Force voice/TTS regeneration + downstream.
    --force-subtitles    Force caption regeneration + downstream.
    --force-motion       Force motion re-planning + video render.
    --force-video        Force full video re-render + downstream.
    --force-bgm          Force BGM re-mix (implies --force-video).
    --force-publish      Force publish package only.
    --scene N            Scope detection to scene N (combine with --force-*).
    --force-scene N      Force-regenerate scene N entirely (overrides lock).

    \b
    EXAMPLES
    ━━━━━━━━
    # Full pipeline from scratch
    ytfactory run "History of Shivaji" --auto

    # Pre-written script, spiritual style, 8-minute target
    ytfactory run "The Silent Force" --script script.md --style spiritual --target-minutes 8 --auto

    # Skip images — place manually later, then re-run
    ytfactory run "Topic" --script script.md --no-images --auto

    # Resume a failed run (agentic graph checkpointing)
    ytfactory run "Topic" --project abc123 --auto

    # Incremental: only rebuild what changed
    ytfactory run "Topic" --project abc123 --resume

    # Replace one image, then auto-detect and rebuild downstream
    cp better.png workspace/jobs/abc123/images/scene-008.png
    ytfactory run "Topic" --project abc123 --resume

    # Force images only
    ytfactory run "Topic" --project abc123 --force-images

    # Force-regenerate scene 8 entirely
    ytfactory run "Topic" --project abc123 --force-scene 8

    # Force just the video for scene 3
    ytfactory run "Topic" --project abc123 --scene 3 --force-video
    """
    from ytfactory.agents.runner import run_pipeline
    from ytfactory.incremental.deps import FORCE_FLAG_TO_STAGE

    force_stages: set[str] = set()
    if force_images:
        force_stages.add(FORCE_FLAG_TO_STAGE["images"])
    if force_narration:
        force_stages.add(FORCE_FLAG_TO_STAGE["narration"])
    if force_subtitles:
        force_stages.add(FORCE_FLAG_TO_STAGE["subtitles"])
    if force_motion or force_video:
        force_stages.add(FORCE_FLAG_TO_STAGE["video"])
    if force_bgm:
        force_stages.add(FORCE_FLAG_TO_STAGE["bgm"])
    if force_publish:
        force_stages.add(FORCE_FLAG_TO_STAGE["publish"])

    run_pipeline(
        topic,
        project_id=project_id,
        language=language,
        auto=auto,
        script_path=script,
        source_url=youtube_url,
        style=style,
        no_images=no_images,
        target_minutes=target_minutes,
        incremental=resume or reuse_assets,
        force_stages=force_stages if force_stages else None,
        scene_filter=scene,
        force_scene=force_scene,
        pipeline_mode=phase or "default",
        atma_refiner_mode=refiner_mode,
    )


@app.command(name="resume")
def resume(
    project_id: str = typer.Argument(..., help="Project ID to resume"),
) -> None:
    """Resume an existing project from Phase 1 (run Phase 2)."""
    from ytfactory.build.pipeline import BuildPipeline

    BuildPipeline().run_resume(project_id)
    _console.print(f"[bold green]✓ Phase 2 complete[/bold green] — project: {project_id}")


if __name__ == "__main__":
    app()
