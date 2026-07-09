"""CLI command: ytfactory benchmark vision-review"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

_console = Console()

benchmark_app = typer.Typer(
    name="benchmark",
    help="Benchmark and compare vision review models.",
    no_args_is_help=True,
)

# Default dataset bundled with the repository
_DEFAULT_DATASET = Path(__file__).parent.parent.parent.parent.parent / "tests" / "benchmark" / "vision_review" / "benchmark.yaml"


@benchmark_app.command(name="vision-review")
def vision_review(
    models: Optional[str] = typer.Option(
        None,
        "--models",
        help=(
            "Comma-separated registry keys to evaluate "
            "(e.g. minicpm_v2_6,qwen2_5_vl_3b). "
            "Default: all installed models with image_review capability."
        ),
    ),
    dataset: Optional[str] = typer.Option(
        None,
        "--dataset",
        help=(
            "Path to a benchmark.yaml file. "
            "Default: tests/benchmark/vision_review/benchmark.yaml"
        ),
    ),
    output_dir: Optional[str] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help=(
            "Directory for result JSON files and report.md. "
            "Default: <dataset-dir>/results/"
        ),
    ),
) -> None:
    """Run vision review models against a labelled image dataset and compare results.

    \b
    EXAMPLES
    ━━━━━━━━
    # Run all installed vision models against the default dataset
    ytfactory benchmark vision-review

    # Compare two specific models
    ytfactory benchmark vision-review --models minicpm_v2_6,qwen2_5_vl_3b

    # Use a custom dataset
    ytfactory benchmark vision-review --dataset path/to/benchmark.yaml
    """
    from ytfactory.benchmark.dataset import BenchmarkDataset
    from ytfactory.benchmark.engine import BenchmarkEngine, resolve_installed_vision_models
    from ytfactory.benchmark.reporter import BenchmarkReporter

    # ── Resolve dataset ───────────────────────────────────────────────────
    dataset_path = Path(dataset) if dataset else _DEFAULT_DATASET
    if not dataset_path.exists():
        _console.print(
            f"[red]✗ Dataset not found: {dataset_path}[/red]\n"
            "Use --dataset to specify a custom benchmark.yaml file."
        )
        raise typer.Exit(1)

    try:
        ds = BenchmarkDataset.load(dataset_path)
    except Exception as exc:
        _console.print(f"[red]✗ Failed to load dataset: {exc}[/red]")
        raise typer.Exit(1)

    # ── Resolve models ────────────────────────────────────────────────────
    if models:
        model_list = [m.strip() for m in models.split(",") if m.strip()]
    else:
        model_list = resolve_installed_vision_models()
        if not model_list:
            _console.print(
                "[yellow]⚠ No installed vision models found with image_review capability.[/yellow]\n"
                "Run [bold]ytfactory setup[/bold] to download models, "
                "or pass [bold]--models[/bold] explicitly."
            )
            raise typer.Exit(1)

    # ── Resolve output directory ──────────────────────────────────────────
    out_path = Path(output_dir) if output_dir else dataset_path.parent / "results"

    # ── Print plan ────────────────────────────────────────────────────────
    _console.print("\n[bold]Vision Review Benchmark[/bold]\n")
    _console.print(f"  Dataset  : {dataset_path}")
    _console.print(f"  Scenes   : {len(ds.scenes)} ({len(ds.bad_scenes)} bad, {len(ds.good_scenes)} good)")
    _console.print(f"  Models   : {', '.join(model_list)}")
    _console.print(f"  Output   : {out_path}")
    _console.print("")

    # ── Run ───────────────────────────────────────────────────────────────
    engine = BenchmarkEngine()
    try:
        report = engine.run(ds, model_list, out_path)
    except Exception as exc:
        _console.print(f"[red]✗ Benchmark failed: {exc}[/red]")
        raise typer.Exit(1)

    # ── Write report ──────────────────────────────────────────────────────
    reporter = BenchmarkReporter()
    md_path = reporter.write(report, out_path)

    # ── Print summary to console ──────────────────────────────────────────
    _console.print("\n[bold]Results[/bold]\n")
    for model_key in model_list:
        m = report.metrics.get(model_key)
        if not m:
            continue
        _console.print(f"  [cyan]{model_key}[/cyan]")
        _console.print(f"    TP={m.tp}  FP={m.fp}  TN={m.tn}  FN={m.fn}")
        _console.print(f"    Precision={m.precision:.1%}  Recall={m.recall:.1%}  F1={m.f1:.1%}  Accuracy={m.accuracy:.1%}")
        _console.print(f"    Avg Latency={m.avg_latency_ms:.0f}ms")
        _console.print(f"    Narrative={m.avg_narrative:.1f}  Technical={m.avg_technical:.1f}  Cinematic={m.avg_cinematic:.1f}")
        _console.print("")

    if report.winner:
        _console.print(f"[green]Winner: {report.winner}[/green]")
    elif len(model_list) > 1:
        _console.print("[yellow]Result: Tied[/yellow]")

    _console.print(f"\n[dim]Reports written to: {out_path}/[/dim]")
    _console.print("[dim]  report.md           — per-model metrics summary[/dim]")
    _console.print("[dim]  comparison.md       — visual scene-by-scene comparison[/dim]")
    _console.print("[dim]  gallery.md          — embedded images + overall leaderboard[/dim]")
    _console.print("[dim]  report-summary.json — structured results[/dim]\n")
