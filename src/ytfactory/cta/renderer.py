"""CTA overlay renderer — Pillow frame generation + FFmpeg composite.

Pipeline:
  1. Generate CTA overlay PNG (full video dimensions, transparent background)
     using Pillow:  glass panel + border + text (subscribe/like/bell).
  2. Composite onto final.mp4 using FFmpeg overlay filter with per-channel
     alpha fade (fade in → hold → fade out).
  3. If CTA sound asset exists, mix it into the audio track at timestamp.
  4. Apply BGM secondary duck: brief volume reduction at CTA timestamp.

The renderer is stateless — each call is idempotent given the same inputs.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from .config import CTAOverlayConfig
from .models import CTAPlacement, CTARenderResult, CTAVariant, CTAZone


# ── Video probe helper ─────────────────────────────────────────────────────────


def _probe_video(path: Path) -> tuple[int, int, float]:
    """Return (width, height, duration) via ffprobe.  Falls back to 1280×720."""
    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(r.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = int(stream.get("width", 1280))
                h = int(stream.get("height", 720))
                return w, h, duration
    except Exception:
        pass
    return 1280, 720, 0.0


# ── Hex color helpers ──────────────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert '#RRGGBB' to (r, g, b)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return r, g, b


def _hex_to_rgba(hex_color: str, alpha: float) -> tuple[int, int, int, int]:
    r, g, b = _hex_to_rgb(hex_color)
    return r, g, b, int(alpha * 255)


# ── Overlay PNG generation ─────────────────────────────────────────────────────


def _generate_cta_overlay(
    config: CTAOverlayConfig,
    placement: CTAPlacement,
    video_width: int,
    video_height: int,
    output_path: Path,
) -> None:
    """Generate CTA overlay PNG (full frame size, transparent bg)."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError(
            "Pillow is required for CTA overlay rendering. Run: uv pip install Pillow"
        )

    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    is_compact = placement.variant == CTAVariant.COMPACT

    # Panel dimensions
    if is_compact:
        panel_w = int(video_width * 0.22)
        panel_h = int(video_height * 0.12)
    else:
        panel_w = int(video_width * 0.38)
        panel_h = int(video_height * 0.18)

    margin = int(video_width * 0.04)

    # Zone-based position
    zone = placement.zone
    if zone == CTAZone.UPPER_LEFT:
        x = margin
        y = margin
    elif zone == CTAZone.UPPER_RIGHT:
        x = video_width - panel_w - margin
        y = margin
    else:  # BOTTOM_CENTER
        x = (video_width - panel_w) // 2
        y = video_height - panel_h - margin - int(video_height * 0.08)

    # Panel background (frosted glass effect via semi-transparent white)
    accent_r, accent_g, accent_b = _hex_to_rgb(config.accent_color)
    panel_fill = (255, 255, 255, int(config.panel_alpha * 255))
    border_color = (accent_r, accent_g, accent_b, int(config.border_alpha * 255))

    # Rounded rectangle panel
    radius = min(12, panel_h // 4)
    draw.rounded_rectangle(
        [(x, y), (x + panel_w, y + panel_h)],
        radius=radius,
        fill=panel_fill,
        outline=border_color,
        width=2,
    )

    # Text layout
    font_size = int(panel_h * (0.22 if is_compact else 0.18))
    font_size_small = max(10, int(font_size * 0.75))

    from typing import Any as _Any

    try:
        main_font: _Any = ImageFont.truetype(f"{config.font}.ttf", font_size)
        small_font: _Any = ImageFont.truetype(f"{config.font}.ttf", font_size_small)
    except Exception:
        try:
            main_font = ImageFont.load_default(size=font_size)  # type: ignore[call-arg]
            small_font = ImageFont.load_default(size=font_size_small)  # type: ignore[call-arg]
        except Exception:
            main_font = ImageFont.load_default()
            small_font = main_font

    text_color = (255, 255, 255, 240)
    accent_text_color = (accent_r, accent_g, accent_b, 240)

    if is_compact:
        # Compact: single line — "Subscribe ♥"
        parts: list[str] = []
        if config.show_subscribe:
            parts.append("Subscribe")
        if config.show_like:
            parts.append("♥")
        if config.show_bell:
            parts.append("🔔")
        cta_text = "  ".join(parts) if parts else "Subscribe"
        _draw_text_centered(
            draw, cta_text, main_font, text_color, x, y, panel_w, panel_h
        )
    else:
        # Full: two lines — action row + subscribe text
        pad = int(panel_h * 0.15)
        line1_y = y + pad

        # Icon row
        icons: list[str] = []
        if config.show_like:
            icons.append("👍")
        if config.show_subscribe:
            icons.append("SUBSCRIBE")
        if config.show_bell:
            icons.append("🔔")
        icon_text = "  ".join(icons) if icons else "SUBSCRIBE"
        draw.text(  # type: ignore[arg-type]
            (x + int(panel_w * 0.08), line1_y),
            icon_text,
            font=main_font,
            fill=accent_text_color,
        )

        # Sub-text row
        line2_y = line1_y + font_size + int(panel_h * 0.08)
        sub_text = "for more reflections"
        draw.text(  # type: ignore[arg-type]
            (x + int(panel_w * 0.08), line2_y),
            sub_text,
            font=small_font,
            fill=text_color,
        )

    img.save(str(output_path), "PNG")


def _draw_text_centered(
    draw: object,
    text: str,
    font: object,
    color: tuple,  # type: ignore[type-arg]
    panel_x: int,
    panel_y: int,
    panel_w: int,
    panel_h: int,
) -> None:
    """Draw text centered within the panel."""
    from PIL import ImageDraw as _PID  # type: ignore[import-untyped]

    assert isinstance(draw, _PID.ImageDraw)
    try:
        bbox = draw.textbbox((0, 0), text, font=font)  # type: ignore[arg-type]
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = len(text) * 8, 16

    tx = panel_x + (panel_w - tw) // 2
    ty = panel_y + (panel_h - th) // 2
    draw.text((tx, ty), text, font=font, fill=color)  # type: ignore[arg-type]


# ── FFmpeg composite ───────────────────────────────────────────────────────────


def _apply_overlay_ffmpeg(
    video_path: Path,
    overlay_png: Path,
    output_path: Path,
    placement: CTAPlacement,
    config: CTAOverlayConfig,
    has_cta_sound: bool,
    cta_sound_path: Path | None,
) -> bool:
    """Composite the overlay PNG onto the video with fade animation via FFmpeg.

    Returns True on success.
    """
    cta_start = placement.timestamp
    cta_end = placement.cta_end
    fade_in = config.fade_in_seconds
    fade_out = config.fade_out_seconds

    # Limit the PNG to exactly the CTA duration, fade in/out relative to its
    # own stream (PTS starts at 0), then shift PTS forward to cta_start so
    # the overlay stream naturally spans [cta_start, cta_end] in the video
    # timeline. This avoids processing the full video worth of PNG frames.
    cta_duration = cta_end - cta_start
    fade_out_start = max(0.0, cta_duration - fade_out)

    # BGM secondary duck: attenuate audio by bgm_secondary_duck_db at CTA window
    duck_db = config.bgm_secondary_duck_db
    audio_filter = (
        f"volume=enable='between(t,{cta_start:.4f},{cta_end:.4f})':"
        f"volume={_db_to_linear(-duck_db):.4f}"
    )

    # Build filter_complex
    filter_complex_parts = [
        # Fade PNG alpha in/out, then shift its PTS to [cta_start, cta_end]
        f"[1:v]format=rgba,"
        f"fade=in:st=0:d={fade_in:.4f}:alpha=1,"
        f"fade=out:st={fade_out_start:.4f}:d={fade_out:.4f}:alpha=1,"
        f"setpts=PTS+{cta_start:.4f}/TB[ovr]",
        # Composite — overlay stream naturally spans the right window
        "[0:v][ovr]overlay=0:0[vout]",
    ]

    filter_complex = ";".join(filter_complex_parts)

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-loop",
        "1",
        "-t",
        f"{cta_duration:.4f}",  # limit PNG to CTA duration — avoids processing full video
        "-i",
        str(overlay_png),
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-af",
        audio_filter,
        "-map",
        "0:a",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(output_path),
    ]

    logger.debug("CTA FFmpeg: {}", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.error(
                "CTA FFmpeg failed (rc={}): {}", result.returncode, result.stderr[-500:]
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("CTA FFmpeg timed out after 300s")
        return False
    except Exception as exc:
        logger.error("CTA FFmpeg exception: {}", exc)
        return False


def _db_to_linear(db: float) -> float:
    return 10 ** (db / 20.0)


# ── Sound asset lookup ─────────────────────────────────────────────────────────


def _find_cta_sound(sound_name: str) -> Path | None:
    """Return path to CTA sound asset, or None if not present."""
    candidates = [
        Path(f"assets/cta/sounds/{sound_name}.mp3"),
        Path(f"assets/cta/sounds/{sound_name}.wav"),
        Path(f"assets/sounds/{sound_name}.mp3"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


# ── Public renderer ────────────────────────────────────────────────────────────


class CTARenderer:
    """Render the CTA overlay onto final.mp4 using Pillow + FFmpeg."""

    def render(
        self,
        video_path: Path,
        output_path: Path,
        placement: CTAPlacement,
        config: CTAOverlayConfig,
    ) -> CTARenderResult:
        """Apply CTA overlay.  Returns CTARenderResult (success/fail + detail)."""
        video_w, video_h, video_dur = _probe_video(video_path)

        if video_dur <= 0:
            return CTARenderResult(
                success=False,
                error="Could not determine video duration via ffprobe",
                template_used=config.template,
            )

        # Clamp CTA timestamp to video bounds
        if placement.timestamp >= video_dur:
            return CTARenderResult(
                success=False,
                error=f"CTA timestamp {placement.timestamp:.1f}s exceeds video duration {video_dur:.1f}s",
                template_used=config.template,
            )

        cta_sound_path = _find_cta_sound(config.sound)
        has_cta_sound = cta_sound_path is not None

        with tempfile.TemporaryDirectory(prefix="ytfactory_cta_") as tmp_dir:
            tmp = Path(tmp_dir)
            overlay_png = tmp / "cta_overlay.png"

            try:
                _generate_cta_overlay(config, placement, video_w, video_h, overlay_png)
            except Exception as exc:
                return CTARenderResult(
                    success=False,
                    error=f"Overlay PNG generation failed: {exc}",
                    template_used=config.template,
                )

            success = _apply_overlay_ffmpeg(
                video_path,
                overlay_png,
                output_path,
                placement,
                config,
                has_cta_sound,
                cta_sound_path,
            )

        if success:
            logger.info(
                "CTA overlay applied: {} variant at {:.1f}s → {}",
                placement.variant.value,
                placement.timestamp,
                output_path,
            )

        return CTARenderResult(
            success=success,
            output_path=str(output_path) if success else "",
            error="" if success else "FFmpeg overlay failed — see logs",
            template_used=config.template,
        )
