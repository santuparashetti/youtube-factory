from rich.console import Console

console = Console()


def research(topic: str):
    """Run research."""
    console.print(f"[cyan]Research:[/cyan] {topic}")