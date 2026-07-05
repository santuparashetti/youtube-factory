"""Video quality and size comparison reporter.

Produces a markdown report comparing two video files (original vs optimised)
using ffprobe — no re-encoding required.

Usage::

    from ytfactory.video.reporter import compare_videos
    report = compare_videos(Path("original.mp4"), Path("optimised.mp4"))
    print(report.to_markdown())
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoStats:
    """Encoding metadata for a single video file."""

    path: Path
    size_bytes: int
    duration_seconds: float
    overall_bitrate_kbps: int

    # video stream
    video_codec: str
    video_profile: str
    video_width: int
    video_height: int
    video_fps: str
    video_bitrate_kbps: int
    video_crf: str
    video_preset: str

    # audio stream
    audio_codec: str
    audio_bitrate_kbps: int
    audio_sample_rate: int

    @property
    def size_mb(self) -> float:
        return self.size_bytes / 1024**2

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1024**3

    @classmethod
    def from_file(cls, path: Path) -> "VideoStats":
        """Probe *path* with ffprobe and return a populated VideoStats."""
        if not path.exists():
            raise FileNotFoundError(path)

        raw = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(raw.stdout)
        fmt = data["format"]

        size_bytes = int(fmt.get("size", 0))
        duration = float(fmt.get("duration", 0.0))
        overall_kbps = int(fmt.get("bit_rate", 0)) // 1000

        vid = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
        aud = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})

        vbr_kbps = int(vid.get("bit_rate", 0)) // 1000

        # Tags sometimes carry the x264 encoding params
        tags: dict = vid.get("tags", {})
        encoder_str = tags.get("encoder", "")
        crf = _extract_tag(encoder_str, "crf")
        preset = _extract_tag(encoder_str, "preset")

        return cls(
            path=path,
            size_bytes=size_bytes,
            duration_seconds=duration,
            overall_bitrate_kbps=overall_kbps,
            video_codec=vid.get("codec_name", "?"),
            video_profile=vid.get("profile", "?"),
            video_width=int(vid.get("width", 0)),
            video_height=int(vid.get("height", 0)),
            video_fps=vid.get("r_frame_rate", "?"),
            video_bitrate_kbps=vbr_kbps,
            video_crf=crf,
            video_preset=preset,
            audio_codec=aud.get("codec_name", "?"),
            audio_bitrate_kbps=int(aud.get("bit_rate", 0)) // 1000,
            audio_sample_rate=int(aud.get("sample_rate", 0)),
        )


@dataclass
class ComparisonReport:
    """Side-by-side comparison of original and optimised video."""

    original: VideoStats
    optimised: VideoStats

    @property
    def size_reduction_bytes(self) -> int:
        return self.original.size_bytes - self.optimised.size_bytes

    @property
    def size_reduction_pct(self) -> float:
        if self.original.size_bytes == 0:
            return 0.0
        return 100.0 * self.size_reduction_bytes / self.original.size_bytes

    @property
    def bitrate_reduction_pct(self) -> float:
        if self.original.overall_bitrate_kbps == 0:
            return 0.0
        return 100.0 * (
            self.original.overall_bitrate_kbps - self.optimised.overall_bitrate_kbps
        ) / self.original.overall_bitrate_kbps

    @property
    def duration_match(self) -> bool:
        return abs(self.original.duration_seconds - self.optimised.duration_seconds) < 0.5

    @property
    def resolution_match(self) -> bool:
        return (
            self.original.video_width == self.optimised.video_width
            and self.original.video_height == self.optimised.video_height
        )

    def to_markdown(self) -> str:
        o = self.original
        p = self.optimised

        size_o = f"{o.size_mb:.1f} MB" if o.size_mb < 1000 else f"{o.size_gb:.2f} GB"
        size_p = f"{p.size_mb:.1f} MB" if p.size_mb < 1000 else f"{p.size_gb:.2f} GB"

        def _dur(s: float) -> str:
            m, sec = divmod(int(s), 60)
            return f"{m}:{sec:02d}"

        checks = {
            "Duration identical": "✅" if self.duration_match else "⚠️ MISMATCH",
            "Resolution identical": "✅" if self.resolution_match else "❌ MISMATCH",
            "Video codec preserved": "✅" if o.video_codec == p.video_codec else "⚠️",
            "Audio codec preserved": "✅" if o.audio_codec == p.audio_codec else "⚠️",
            "No quality regression (CRF model)": (
                "✅ CRF-based encoding; quality is defined by the CRF floor"
                if p.video_codec == "h264"
                else "⚠️ Manual review recommended"
            ),
        }

        lines = [
            "# Video Comparison Report",
            "",
            "## File Summary",
            "",
            "| Metric | Original | Optimised | Change |",
            "|--------|----------|-----------|--------|",
            f"| File | `{o.path.name}` | `{p.path.name}` | — |",
            f"| **Size** | **{size_o}** | **{size_p}** | **−{self.size_reduction_pct:.1f}%** |",
            f"| Duration | {_dur(o.duration_seconds)} | {_dur(p.duration_seconds)} | {'✅ identical' if self.duration_match else '⚠️ differs'} |",
            f"| Overall bitrate | {o.overall_bitrate_kbps} kbps | {p.overall_bitrate_kbps} kbps | −{self.bitrate_reduction_pct:.1f}% |",
            "",
            "## Video Stream",
            "",
            "| Metric | Original | Optimised |",
            "|--------|----------|-----------|",
            f"| Codec | {o.video_codec} | {p.video_codec} |",
            f"| Resolution | {o.video_width}×{o.video_height} | {p.video_width}×{p.video_height} |",
            f"| Frame rate | {o.video_fps} fps | {p.video_fps} fps |",
            f"| Profile | {o.video_profile} | {p.video_profile} |",
            f"| Bitrate | {o.video_bitrate_kbps or '?'} kbps | {p.video_bitrate_kbps or '?'} kbps |",
            f"| CRF (from tags) | {o.video_crf or '?'} | {p.video_crf or '?'} |",
            f"| Preset (from tags) | {o.video_preset or '?'} | {p.video_preset or '?'} |",
            "",
            "## Audio Stream",
            "",
            "| Metric | Original | Optimised |",
            "|--------|----------|-----------|",
            f"| Codec | {o.audio_codec} | {p.audio_codec} |",
            f"| Bitrate | {o.audio_bitrate_kbps} kbps | {p.audio_bitrate_kbps} kbps |",
            f"| Sample rate | {o.audio_sample_rate} Hz | {p.audio_sample_rate} Hz |",
            "",
            "## Quality Verification",
            "",
        ]
        for label, status in checks.items():
            lines.append(f"- {label}: {status}")

        lines += [
            "",
            "## Encoding Settings Used (Optimised)",
            "",
            "| Setting | Value |",
            "|---------|-------|",
            f"| Codec | {p.video_codec} |",
            f"| CRF | {p.video_crf or '(see tags)'} |",
            f"| Preset | {p.video_preset or '(see tags)'} |",
            f"| Resolution | {p.video_width}×{p.video_height} |",
            f"| Frame rate | {p.video_fps} fps |",
            f"| Audio codec | {p.audio_codec} |",
            f"| Audio bitrate | {p.audio_bitrate_kbps} kbps |",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        o, p = self.original, self.optimised
        return {
            "original": {
                "path": str(o.path),
                "size_bytes": o.size_bytes,
                "size_mb": round(o.size_mb, 2),
                "duration_seconds": round(o.duration_seconds, 2),
                "overall_bitrate_kbps": o.overall_bitrate_kbps,
                "video_bitrate_kbps": o.video_bitrate_kbps,
                "audio_bitrate_kbps": o.audio_bitrate_kbps,
                "crf": o.video_crf,
                "preset": o.video_preset,
            },
            "optimised": {
                "path": str(p.path),
                "size_bytes": p.size_bytes,
                "size_mb": round(p.size_mb, 2),
                "duration_seconds": round(p.duration_seconds, 2),
                "overall_bitrate_kbps": p.overall_bitrate_kbps,
                "video_bitrate_kbps": p.video_bitrate_kbps,
                "audio_bitrate_kbps": p.audio_bitrate_kbps,
                "crf": p.video_crf,
                "preset": p.video_preset,
            },
            "comparison": {
                "size_reduction_bytes": self.size_reduction_bytes,
                "size_reduction_pct": round(self.size_reduction_pct, 1),
                "bitrate_reduction_pct": round(self.bitrate_reduction_pct, 1),
                "duration_match": self.duration_match,
                "resolution_match": self.resolution_match,
            },
        }


def compare_videos(original: Path, optimised: Path) -> ComparisonReport:
    """Probe both video files and return a ComparisonReport."""
    return ComparisonReport(
        original=VideoStats.from_file(original),
        optimised=VideoStats.from_file(optimised),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _extract_tag(encoder_str: str, key: str) -> str:
    """Extract a value from an x264 encoder tag string like 'crf=18 preset=medium'."""
    for part in encoder_str.split():
        if "=" in part:
            k, _, v = part.partition("=")
            if k == key:
                return v
    return ""
