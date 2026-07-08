"""Bootstrap Reporter — writes environment-report.json and bootstrap-manifest.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from .models import BootstrapResult, CheckStatus


def write_environment_report(result: BootstrapResult, base_dir: Path | None = None) -> Path:
    """Write environment-report.json to the project root. Returns the path."""
    root = base_dir or Path.cwd()
    report_path = root / "environment-report.json"

    data: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "success": result.success,
        "summary": {
            "total": len(result.checks),
            "ok": sum(1 for c in result.checks if c.status == CheckStatus.OK),
            "warning": sum(1 for c in result.checks if c.status == CheckStatus.WARNING),
            "error": sum(1 for c in result.checks if c.status == CheckStatus.ERROR),
            "repaired": sum(1 for c in result.checks if c.status == CheckStatus.REPAIRED),
            "skipped": sum(1 for c in result.checks if c.status == CheckStatus.SKIPPED),
        },
        "checks": [
            {
                "name": c.name,
                "status": c.status.value,
                "message": c.message,
                "detail": c.detail,
                "repaired": c.repaired,
            }
            for c in result.checks
        ],
        "repairs": result.repairs,
        "environment": result.environment,
    }

    try:
        report_path.write_text(json.dumps(data, indent=2))
        logger.info("Environment report: {}", report_path)
    except OSError as exc:
        logger.warning("Cannot write environment report: {}", exc)

    return report_path


def read_environment_report(base_dir: Path | None = None) -> dict[str, Any] | None:
    root = base_dir or Path.cwd()
    path = root / "environment-report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None
