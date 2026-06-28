from pathlib import Path

from rich.console import Console

from ytfactory.import_script.pipeline import ImportScriptPipeline

console = Console()


def import_script(
    project_id: str,
    script_file: str,
):
    """Import an existing script into a project."""

    ImportScriptPipeline().run(
        project_id,
        Path(script_file),
    )

    console.print("[green]✓ Script imported[/green]")