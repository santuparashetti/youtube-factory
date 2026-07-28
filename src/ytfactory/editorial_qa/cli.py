import typer
from rich.console import Console
from rich.table import Table

from ytfactory.config.settings import Settings
from ytfactory.editorial_qa.pipeline import EditorialQAPipeline
from ytfactory.editorial_qa.promoter import PatternPromoter

console = Console()

qa_app = typer.Typer(
    help="Pattern Promoter proposals — human approve/dismiss gate. Never auto-applied."
)


def editorial_qa(project_id: str) -> None:
    """Run the Editorial QA stage on an existing project.

    Reads workspace/jobs/<project-id>/script/script.md (post Structural
    Retention Pass), runs the 6-check reviewer, appends to the cross-project
    ledger, and evaluates the Pattern Promoter. Flags only — never rewrites,
    gates, blocks, rejects, or reverts anything.
    """
    EditorialQAPipeline(Settings()).run(project_id)


@qa_app.command(name="list")
def list_pending() -> None:
    """List pending Pattern Promoter proposals awaiting a human decision."""
    pending = PatternPromoter(Settings()).list_pending()
    if not pending:
        console.print("[dim]No pending proposals.[/dim]")
        return

    table = Table(title="Pending Editorial QA Proposals")
    table.add_column("Check")
    table.add_column("Flag rate")
    table.add_column("Summary")
    for name, p in pending.items():
        table.add_row(name, f"{p['flag_count']}/{p['total']}", p.get("summary", ""))
    console.print(table)

    for name, p in pending.items():
        console.print(
            f"\n[bold]{name}[/bold] — proposed addition "
            f"(nothing applied automatically):\n{p.get('proposed_prompt_addition', '')}"
        )


@qa_app.command(name="approve")
def approve(check_name: str) -> None:
    """Approve a proposal. Does NOT edit any prompt file — you (or an agent
    you direct) still add the text yourself."""
    proposal = PatternPromoter(Settings()).approve(check_name)
    if proposal is None:
        console.print(f"[yellow]No pending proposal for '{check_name}'.[/yellow]")
        return
    console.print(
        f"[green]Approved.[/green] Add this text to the relevant prompt yourself:\n\n"
        f"{proposal['proposed_prompt_addition']}"
    )


@qa_app.command(name="dismiss")
def dismiss(check_name: str) -> None:
    """Dismiss a proposal. Starts a cooldown — won't re-propose the same
    check until the cooldown passes, unless its flag-rate rises."""
    proposal = PatternPromoter(Settings()).dismiss(check_name)
    if proposal is None:
        console.print(f"[yellow]No pending proposal for '{check_name}'.[/yellow]")
        return
    console.print(f"[dim]Dismissed '{check_name}'.[/dim]")
