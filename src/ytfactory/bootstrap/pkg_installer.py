"""ML package auto-installer — installs heavy/optional packages during ytfactory setup.

Packages in this module are intentionally NOT in pyproject.toml because they
ship platform-specific wheels (CUDA vs CPU) or are very large. This module
detects which ones are needed based on .env settings and installs them
automatically so new machines need no manual pip commands.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

from .models import CheckResult, CheckStatus


def install_ml_packages() -> list[CheckResult]:
    """Install Kokoro, WhisperX, and PyTorch based on configured providers.

    Idempotent: skips any package that is already importable.
    Installs PyTorch CPU by default; existing CUDA installs are left untouched.
    """
    results: list[CheckResult] = []

    tts_provider = _read_setting("tts_provider", "kokoro")
    whisperx_enabled = _read_bool("whisperx_enabled", True)
    needs_torch = tts_provider == "kokoro" or whisperx_enabled

    # ── PyTorch (shared dep for both Kokoro and WhisperX) ─────────────────────
    if needs_torch:
        if not _importable("torch"):
            results.extend(
                _pip_install(
                    [
                        "torch",
                        "torchaudio",
                        "--index-url",
                        "https://download.pytorch.org/whl/cpu",
                    ],
                    label="pkg:torch",
                    description="PyTorch (CPU)",
                )
            )
        else:
            results.append(
                CheckResult(
                    name="pkg:torch",
                    status=CheckStatus.OK,
                    message="PyTorch already installed",
                )
            )

    # ── Kokoro TTS packages ───────────────────────────────────────────────────
    if tts_provider == "kokoro":
        for pkg, label in [("kokoro", "pkg:kokoro"), ("soundfile", "pkg:soundfile")]:
            if not _importable(pkg):
                results.extend(
                    _pip_install([pkg], label=label, description=pkg)
                )
            else:
                results.append(
                    CheckResult(
                        name=label,
                        status=CheckStatus.OK,
                        message=f"{pkg} already installed",
                    )
                )

    # ── WhisperX forced alignment ─────────────────────────────────────────────
    if whisperx_enabled:
        if not _importable("whisperx"):
            results.extend(
                _pip_install(["whisperx"], label="pkg:whisperx", description="WhisperX")
            )
        else:
            results.append(
                CheckResult(
                    name="pkg:whisperx",
                    status=CheckStatus.OK,
                    message="WhisperX already installed",
                )
            )

    return results


# ── Helpers ────────────────────────────────────────────────────────────────────


def _importable(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _pip_install(
    packages: list[str], *, label: str, description: str
) -> list[CheckResult]:
    # Use `uv pip install` so packages always land in the active uv-managed venv.
    # Falling back to `sys.executable -m pip install` risks installing to the
    # system/user site-packages when pip is absent from the venv (uv default).
    cmd = ["uv", "pip", "install"] + packages
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            return [
                CheckResult(
                    name=label,
                    status=CheckStatus.OK,
                    message=f"Installed {description}",
                )
            ]
        return [
            CheckResult(
                name=label,
                status=CheckStatus.WARNING,
                message=f"Failed to install {description}",
                detail=(r.stdout + r.stderr)[-500:],
            )
        ]
    except Exception as exc:
        return [
            CheckResult(
                name=label,
                status=CheckStatus.WARNING,
                message=f"Install error: {description}",
                detail=str(exc),
            )
        ]


def _read_setting(key: str, default: str) -> str:
    try:
        from ytfactory.config.settings import Settings  # noqa: PLC0415

        return str(getattr(Settings(), key, default))
    except Exception:
        return default


def _read_bool(key: str, default: bool) -> bool:
    try:
        from ytfactory.config.settings import Settings  # noqa: PLC0415

        return bool(getattr(Settings(), key, default))
    except Exception:
        return default
