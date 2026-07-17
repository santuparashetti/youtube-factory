from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from ytfactory.create.pipeline import CreatePipeline

console = Console()


def create(
    title: str,
    script: Optional[Path] = typer.Option(
        None,
        "--script",
        help="Path to a raw transcript file. Imports it automatically after creating the project.",
    ),
) -> None:
    """Create a new project.

    Pass --script to import a transcript immediately (equivalent to
    create + import-script in one step). The transcript will be normalized
    and enhanced when you run build or normalize.
    """
    project = CreatePipeline().run(title)

    console.print()
    console.print(f"[green]✓[/green] Project created: {project.id}")
    console.print(f"  workspace/jobs/{project.id}")

    if script is not None:
        from ytfactory.import_script.pipeline import ImportScriptPipeline

        if not script.exists():
            console.print(f"[red]✗ Script file not found: {script}[/red]")
            raise typer.Exit(1)

        ImportScriptPipeline().run(project.id, script)
        console.print(f"[green]✓[/green] Script imported from {script}")
        console.print(
            "  Run [bold]ytfactory normalize[/bold] or "
            "[bold]ytfactory build[/bold] to continue."
        )
