"""Report generators — daily, weekly, monthly."""

from __future__ import annotations

from pathlib import Path

from video_core.visual_intelligence.analytics.collector import AnalyticsCollector
from video_core.visual_intelligence.analytics.exporter import export_dashboard


def generate_report(
    collector: AnalyticsCollector,
    period: str = "daily",
    output_dir: Path | None = None,
    fmt: str = "json",
) -> Path:
    dashboard = collector.build_dashboard()
    dashboard.pipeline_summary["period"] = period
    if output_dir is None:
        output_dir = Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "json" if fmt == "json" else "md"
    path = output_dir / f"visual-intelligence-{period}-{dashboard.generated_at[:10]}.{suffix}"
    export_dashboard(dashboard, path, fmt=fmt)
    return path
