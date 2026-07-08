"""Self-Healing Engine — detects and repairs common issues automatically."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from loguru import logger

from .models import CheckResult, CheckStatus
from .workspace import _REQUIRED_DIRS


def heal(base_dir: Path | None = None) -> list[CheckResult]:
    """Run all self-healing checks. Returns one result per issue found/repaired."""
    root = base_dir or Path.cwd()
    results: list[CheckResult] = []
    results.extend(_heal_directories(root))
    results.extend(_heal_permissions(root))
    results.extend(_heal_symlinks(root))
    return results


def _heal_directories(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for rel in _REQUIRED_DIRS:
        target = root / rel
        if not target.exists():
            try:
                target.mkdir(parents=True, exist_ok=True)
                logger.info("Self-heal: created missing directory {}", rel)
                results.append(CheckResult(
                    name=f"heal:dir:{rel}",
                    status=CheckStatus.REPAIRED,
                    message=f"Created missing directory: {rel}/",
                    repaired=True,
                ))
            except OSError as exc:
                results.append(CheckResult(
                    name=f"heal:dir:{rel}",
                    status=CheckStatus.ERROR,
                    message=f"Cannot create {rel}/",
                    detail=str(exc),
                ))
    return results


def _heal_permissions(root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    for rel in _REQUIRED_DIRS:
        target = root / rel
        if not target.exists():
            continue
        if not os.access(target, os.W_OK):
            try:
                current = target.stat().st_mode
                target.chmod(current | stat.S_IWUSR | stat.S_IWGRP)
                logger.info("Self-heal: fixed permissions on {}", rel)
                results.append(CheckResult(
                    name=f"heal:perms:{rel}",
                    status=CheckStatus.REPAIRED,
                    message=f"Fixed permissions on {rel}/",
                    repaired=True,
                ))
            except OSError as exc:
                results.append(CheckResult(
                    name=f"heal:perms:{rel}",
                    status=CheckStatus.ERROR,
                    message=f"Cannot fix permissions on {rel}/",
                    detail=str(exc),
                ))
    return results


def _heal_symlinks(root: Path) -> list[CheckResult]:
    """Remove broken symlinks under workspace/."""
    results: list[CheckResult] = []
    workspace = root / "workspace"
    if not workspace.exists():
        return results
    for item in workspace.rglob("*"):
        if item.is_symlink() and not item.exists():
            try:
                item.unlink()
                logger.info("Self-heal: removed broken symlink {}", item)
                results.append(CheckResult(
                    name=f"heal:symlink:{item.name}",
                    status=CheckStatus.REPAIRED,
                    message=f"Removed broken symlink: {item.relative_to(root)}",
                    repaired=True,
                ))
            except OSError as exc:
                results.append(CheckResult(
                    name=f"heal:symlink:{item.name}",
                    status=CheckStatus.ERROR,
                    message=f"Cannot remove broken symlink: {item.name}",
                    detail=str(exc),
                ))
    return results
