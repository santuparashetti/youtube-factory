from rich.console import Console

from ytfactory.research.pipeline import ResearchPipeline

console = Console()


def research(project_id: str):
    console.print(f"[cyan]Researching:[/cyan] {project_id}")

    ResearchPipeline().run(project_id)

    console.print("[green]✓ Research completed[/green]")