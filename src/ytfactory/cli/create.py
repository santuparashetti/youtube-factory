from pathlib import Path
import json
import typer
from rich.console import Console
from slugify import slugify

console = Console()


def create_project(title: str):
    """Create a new YouTube Factory project."""

    project_id = slugify(title)

    root = Path("workspace/jobs") / project_id

    for folder in [
        "assets",
        "cache",
        "images",
        "audio",
        "output",
        "logs",
    ]:
        (root / folder).mkdir(parents=True, exist_ok=True)

    project = {
        "id": project_id,
        "title": title,
        "status": "CREATED",
        "language": "en",
    }

    with open(root / "project.json", "w") as f:
        json.dump(project, f, indent=2)

    console.print(f"[green]✓ Project created:[/green] {root}")