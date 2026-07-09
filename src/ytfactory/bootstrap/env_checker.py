"""Environment checker — verifies Python, FFmpeg, Git, and system deps."""

from __future__ import annotations

import subprocess
import sys

from .models import CheckResult, CheckStatus


def check_environment() -> list[CheckResult]:
    """Check all required system dependencies."""
    results: list[CheckResult] = []
    results.extend(_check_python())
    results.extend(_check_ffmpeg())
    results.extend(_check_git())
    results.extend(_check_torch())
    results.extend(_check_fonts())
    return results


def _run(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)


def _check_python() -> list[CheckResult]:
    ver = sys.version_info
    if ver < (3, 10):
        return [
            CheckResult(
                name="env:python",
                status=CheckStatus.ERROR,
                message=f"Python {ver.major}.{ver.minor} found — Python 3.10+ required",
            )
        ]
    return [
        CheckResult(
            name="env:python",
            status=CheckStatus.OK,
            message=f"Python {ver.major}.{ver.minor}.{ver.micro}",
        )
    ]


def _check_ffmpeg() -> list[CheckResult]:
    ok, out = _run(["ffmpeg", "-version"])
    if not ok:
        return [
            CheckResult(
                name="env:ffmpeg",
                status=CheckStatus.ERROR,
                message="FFmpeg not found — install ffmpeg",
                detail=out,
            )
        ]
    version_line = out.splitlines()[0] if out else "unknown"
    ok2, _ = _run(["ffprobe", "-version"])
    results = [
        CheckResult(
            name="env:ffmpeg",
            status=CheckStatus.OK,
            message=version_line[:80],
        )
    ]
    if not ok2:
        results.append(
            CheckResult(
                name="env:ffprobe",
                status=CheckStatus.ERROR,
                message="ffprobe not found — install ffmpeg-tools",
            )
        )
    else:
        results.append(
            CheckResult(
                name="env:ffprobe",
                status=CheckStatus.OK,
                message="ffprobe available",
            )
        )
    return results


def _check_git() -> list[CheckResult]:
    ok, out = _run(["git", "--version"])
    if not ok:
        return [
            CheckResult(
                name="env:git",
                status=CheckStatus.WARNING,
                message="git not found (optional for production)",
            )
        ]
    return [
        CheckResult(
            name="env:git",
            status=CheckStatus.OK,
            message=out.strip()[:60],
        )
    ]


def _check_torch() -> list[CheckResult]:
    try:
        import torch  # type: ignore[import]

        ver = torch.__version__
        cuda = torch.cuda.is_available()
        return [
            CheckResult(
                name="env:torch",
                status=CheckStatus.OK,
                message=f"PyTorch {ver}"
                + (" (CUDA available)" if cuda else " (CPU only)"),
            )
        ]
    except ImportError:
        return [
            CheckResult(
                name="env:torch",
                status=CheckStatus.WARNING,
                message="PyTorch not installed — required for Kokoro TTS and WhisperX",
                detail="Install: uv pip install torch --index-url https://download.pytorch.org/whl/cpu",
            )
        ]


def _check_fonts() -> list[CheckResult]:
    """Check that at least one subtitle font is available."""
    font_names = ["Arial", "DejaVu Sans", "Liberation Sans", "Noto Sans"]
    ok, out = _run(["fc-list"])
    if not ok:
        return [
            CheckResult(
                name="env:fonts",
                status=CheckStatus.WARNING,
                message="fc-list not available — cannot verify fonts",
            )
        ]
    installed = out.lower()
    for name in font_names:
        if name.lower().replace(" ", "") in installed.replace(" ", ""):
            return [
                CheckResult(
                    name="env:fonts",
                    status=CheckStatus.OK,
                    message=f"Font '{name}' available",
                )
            ]
    return [
        CheckResult(
            name="env:fonts",
            status=CheckStatus.WARNING,
            message="No standard subtitle fonts found — subtitles may fall back to default font",
            detail="Install: apt install fonts-liberation OR fonts-dejavu",
        )
    ]
