"""DoctorPipeline — full health check for the running environment."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from ytfactory.bootstrap.engine import BootstrapEngine
from ytfactory.bootstrap.models import CheckStatus
from ytfactory.bootstrap.version_manager import load_manifest

from .models import DoctorReport

console = Console()

_STATUS_STYLE = {
    CheckStatus.OK: "[green]✓[/green]",
    CheckStatus.WARNING: "[yellow]⚠[/yellow]",
    CheckStatus.ERROR: "[red]✗[/red]",
    CheckStatus.REPAIRED: "[cyan]↻[/cyan]",
    CheckStatus.SKIPPED: "[dim]−[/dim]",
}


class DoctorPipeline:
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path.cwd()

    def run(self) -> DoctorReport:
        console.print("\n[bold]YouTube Factory — Doctor[/bold]\n")

        engine = BootstrapEngine(self._base_dir)
        result = engine.doctor()

        # Render results table
        table = Table(show_header=True, header_style="bold")
        table.add_column("Status", width=6)
        table.add_column("Check", min_width=30)
        table.add_column("Message")

        for check in result.checks:
            icon = _STATUS_STYLE.get(check.status, check.status.value)
            table.add_row(icon, check.name, check.message)

        console.print(table)

        # Show manifest info
        manifest = load_manifest(self._base_dir)
        if manifest:
            console.print(
                f"\n[dim]Bootstrap manifest: v{manifest.get('bootstrap_version', '?')} "
                f"(validated {manifest.get('validated_at', '?')[:10]})[/dim]"
            )

        # Summary
        errors = result.errors
        warnings = result.warnings
        if errors:
            console.print(
                f"\n[red]✗ {len(errors)} error(s) found — run 'ytfactory repair' or 'ytfactory setup'[/red]"
            )
        elif warnings:
            console.print(
                f"\n[yellow]⚠ {len(warnings)} warning(s) — system may work with reduced functionality[/yellow]"
            )
        else:
            console.print("\n[green]✓ All checks passed — system healthy[/green]")

        report = DoctorReport()
        report.checks = result.checks
        return report
