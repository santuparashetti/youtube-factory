"""Workspace bootstrap — creates and validates all required directories."""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from .models import CheckResult, CheckStatus

# All directories that must exist at runtime
_REQUIRED_DIRS = [
    "workspace",
    "workspace/jobs",
    "workspace/music",
    "cache",
    "models",
    "logs",
    "assets",
    "temp",
]


def bootstrap_workspace(base_dir: Path | None = None) -> list[CheckResult]:
    """Create all required workspace directories. Idempotent."""
    root = base_dir or Path.cwd()
    results: list[CheckResult] = []

    for rel in _REQUIRED_DIRS:
        target = root / rel
        if target.exists():
            results.append(CheckResult(
                name=f"dir:{rel}",
                status=CheckStatus.OK,
                message=f"{rel}/ exists",
            ))
        else:
            try:
                target.mkdir(parents=True, exist_ok=True)
                logger.info("Created directory: {}", rel)
                results.append(CheckResult(
                    name=f"dir:{rel}",
                    status=CheckStatus.REPAIRED,
                    message=f"{rel}/ created",
                    repaired=True,
                ))
            except OSError as exc:
                results.append(CheckResult(
                    name=f"dir:{rel}",
                    status=CheckStatus.ERROR,
                    message=f"Cannot create {rel}/",
                    detail=str(exc),
                ))

    # Ensure workspace/.gitkeep exists so git tracks the dir
    gitkeep = root / "workspace" / ".gitkeep"
    if not gitkeep.exists():
        try:
            gitkeep.touch()
        except OSError:
            pass

    return results


def validate_workspace(base_dir: Path | None = None) -> list[CheckResult]:
    """Validate that all required directories exist and are writable."""
    root = base_dir or Path.cwd()
    results: list[CheckResult] = []

    for rel in _REQUIRED_DIRS:
        target = root / rel
        if not target.exists():
            results.append(CheckResult(
                name=f"dir:{rel}",
                status=CheckStatus.ERROR,
                message=f"Missing directory: {rel}/",
                detail="Run 'ytfactory setup' to create it.",
            ))
        elif not os.access(target, os.W_OK):
            results.append(CheckResult(
                name=f"dir:{rel}",
                status=CheckStatus.ERROR,
                message=f"Not writable: {rel}/",
            ))
        else:
            results.append(CheckResult(
                name=f"dir:{rel}",
                status=CheckStatus.OK,
                message=f"{rel}/ OK",
            ))

    return results
