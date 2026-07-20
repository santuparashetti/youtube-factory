"""Analytics exporter — JSON and Markdown exports."""

from __future__ import annotations

import json
from pathlib import Path

from video_core.visual_intelligence.analytics.models import DashboardModel


def export_dashboard(dashboard: DashboardModel, output_path: Path, fmt: str = "json") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output_path.write_text(json.dumps(dashboard.__dict__, indent=2, default=str), encoding="utf-8")
    elif fmt == "markdown":
        lines = [
            f"# Visual Intelligence Dashboard — {dashboard.generated_at}",
            "",
            "## Pipeline Summary",
            "",
            json.dumps(dashboard.pipeline_summary, indent=2),
            "",
            "## Provider Comparison",
            "",
        ]
        for b in dashboard.provider_comparison:
            lines.append(
                f"- **{b.provider_name}**: score={b.avg_score:.1f}, latency={b.avg_latency_ms:.0f}ms, "
                f"failure_rate={b.failure_rate:.2%}, samples={b.sample_count}"
            )
        lines.extend([
            "",
            "## Top Failure Categories",
            "",
        ])
        for item in dashboard.top_failure_categories:
            lines.append(f"- {item['category']}: {item['count']}")
        lines.extend([
            "",
            "## Remediation Summary",
            "",
            json.dumps(dashboard.remediation_summary, indent=2),
            "",
        ])
        output_path.write_text("\n".join(lines), encoding="utf-8")
    else:
        raise ValueError(f"Unsupported export format: {fmt}")
