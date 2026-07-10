"""Environment checker — verifies Python, FFmpeg, Git, and system deps."""

from __future__ import annotations

import importlib.util
import subprocess
import sys

from .models import CheckResult, CheckStatus


def check_environment() -> list[CheckResult]:
    """Check all required system dependencies."""
    results: list[CheckResult] = []
    results.extend(_check_python())
    results.extend(_check_ffmpeg())
    results.extend(_check_git())
    results.extend(_check_espeak_ng())
    results.extend(_check_torch())
    results.extend(_check_kokoro())
    results.extend(_check_soundfile())
    results.extend(_check_whisperx())
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


def _check_espeak_ng() -> list[CheckResult]:
    ok, out = _run(["espeak-ng", "--version"])
    if not ok:
        return [
            CheckResult(
                name="env:espeak-ng",
                status=CheckStatus.WARNING,
                message="espeak-ng not found — required for Kokoro TTS phoneme generation",
                detail="Install: sudo apt install espeak-ng",
            )
        ]
    return [
        CheckResult(
            name="env:espeak-ng",
            status=CheckStatus.OK,
            message=out.splitlines()[0][:80] if out else "espeak-ng available",
        )
    ]


def _importable(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _check_kokoro() -> list[CheckResult]:
    tts_provider = _read_setting("tts_provider", "kokoro")
    if not _importable("kokoro"):
        status = CheckStatus.ERROR if tts_provider == "kokoro" else CheckStatus.WARNING
        return [
            CheckResult(
                name="env:kokoro",
                status=status,
                message="kokoro not installed — run: ytfactory setup",
            )
        ]
    return [CheckResult(name="env:kokoro", status=CheckStatus.OK, message="kokoro available")]


def _check_soundfile() -> list[CheckResult]:
    if not _importable("soundfile"):
        return [
            CheckResult(
                name="env:soundfile",
                status=CheckStatus.WARNING,
                message="soundfile not installed — run: uv sync",
            )
        ]
    return [CheckResult(name="env:soundfile", status=CheckStatus.OK, message="soundfile available")]


def _check_whisperx() -> list[CheckResult]:
    whisperx_enabled = _read_bool("whisperx_enabled", True)
    if not _importable("whisperx"):
        status = CheckStatus.WARNING if not whisperx_enabled else CheckStatus.ERROR
        return [
            CheckResult(
                name="env:whisperx",
                status=status,
                message="whisperx not installed — run: ytfactory setup",
            )
        ]
    return [CheckResult(name="env:whisperx", status=CheckStatus.OK, message="whisperx available")]


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
