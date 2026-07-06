"""PauseInjector — orchestrates thought-block TTS synthesis with contemplative silence gaps.

Flow for each scene narration:

  1. ThoughtAnalyzer groups the narration into semantic thought blocks.
  2. For each block:
       a. SpeechOptimizer restructures the block text into TTS-ready phrasing.
       b. TTS provider synthesises the block → temp MP3 + word boundaries.
       c. Word boundaries are shifted by the cumulative time offset so far.
       d. The LAST boundary's ``end`` is extended to cover the coming silence
          so subtitles remain visible throughout the pause, not just until
          the last spoken word.
       e. A silence segment is appended (FFmpeg anullsrc) for ``pause_ms`` ms.
  3. All audio segments are concatenated into the final output MP3.
  4. The master word-boundaries list (with correct absolute timestamps) is returned.

Downstream effects (automatic, no extra code needed):
  • Scene duration — VideoRenderer reads actual audio duration via ffprobe.
  • Subtitle timing — SubtitleEngine reads timing.json boundaries;
                      last-word end covers the silence so subtitles persist.
  • BGM mixing    — BGMMixer reads total video duration via ffprobe.
  • Camera motion — zoompan runs for the full (extended) audio duration,
                    naturally slower when more silence is present.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from .thought_analyzer import ThoughtAnalyzer


# ---------------------------------------------------------------------------
# FFmpeg helpers
# ---------------------------------------------------------------------------

def _probe_duration(path: Path) -> float:
    """Return audio duration in seconds via ffprobe. Returns 0.0 on error."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(path),
            ],
            capture_output=True, text=True, check=True, timeout=30,
        )
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def _generate_silence(path: Path, duration_seconds: float) -> None:
    """Write a silent MP3 of exactly duration_seconds.

    Uses 24 kHz mono to match Edge TTS output format.
    """
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=sample_rate=24000:channel_layout=mono",
            "-t", f"{duration_seconds:.4f}",
            "-c:a", "libmp3lame",
            "-q:a", "9",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )


def _concat_segments(segments: list[Path], output_path: Path) -> None:
    """Concatenate audio segments using FFmpeg concat demuxer, re-encoding to MP3 Q2.

    Re-encoding (rather than -c copy) ensures gap-free concatenation regardless
    of minor sample-rate or frame-boundary differences between segments.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for seg in segments:
            f.write(f"file '{seg.resolve()}'\n")
        filelist = Path(f.name)

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(filelist),
                "-c:a", "libmp3lame",
                "-q:a", "2",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
    finally:
        filelist.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class PauseInjector:
    """Orchestrates thought-block TTS synthesis with contemplative silence gaps.

    Instantiate once at module level::

        _pacer = PauseInjector()

    Then call per scene::

        output_path, boundaries = _pacer.generate(
            narration, output_path, optimizer, provider,
            profile="spiritual", ...
        )
    """

    def __init__(self) -> None:
        self._analyzer = ThoughtAnalyzer()

    def generate(
        self,
        narration: str,
        output_path: Path,
        optimizer,          # SpeechOptimizer — duck-typed to avoid circular import
        provider,           # TTSProvider — duck-typed
        *,
        profile: str = "spiritual",
        style: str = "spiritual",
        language: str = "en",
        scene_position: float = 0.5,
        keywords: list[str] | None = None,
    ) -> tuple[Path, list[dict]]:
        """Synthesise *narration* with contemplative thought-block pauses.

        Returns ``(output_path, master_boundaries)`` where each boundary is
        ``{word, start, end}`` with timestamps already shifted to account for
        inserted silence.  The last word of each block has its ``end``
        extended to cover the following silence so subtitles remain visible
        during the pause.
        """
        blocks = self._analyzer.analyze(narration, profile)

        if not blocks:
            logger.warning("PauseInjector: no thought blocks found — falling back to plain synthesis")
            return self._fallback(narration, output_path, optimizer, provider,
                                  style=style, language=language,
                                  scene_position=scene_position, keywords=keywords)

        # Single thought block: synthesise directly without silence machinery.
        if len(blocks) == 1:
            logger.debug("PauseInjector: single thought block — no inter-block silence")
            return self._synthesise_block(
                blocks[0].text, output_path, optimizer, provider,
                style=style, language=language,
                scene_position=scene_position, keywords=keywords,
            )

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            segments: list[Path] = []
            all_boundaries: list[dict] = []
            time_offset = 0.0

            for i, block in enumerate(blocks):
                block_audio = tmp / f"block_{i:03d}.mp3"

                _, block_boundaries = self._synthesise_block(
                    block.text, block_audio, optimizer, provider,
                    style=style, language=language,
                    scene_position=scene_position, keywords=keywords,
                )

                # Shift this block's word boundaries by the cumulative time offset.
                shifted: list[dict] = [
                    {
                        "word": b["word"],
                        "start": round(b["start"] + time_offset, 4),
                        "end": round(b["end"] + time_offset, 4),
                    }
                    for b in block_boundaries
                ]

                audio_dur = _probe_duration(block_audio)
                time_offset += audio_dur
                segments.append(block_audio)

                is_last = i == len(blocks) - 1
                if not is_last and block.pause_ms > 0:
                    silence_sec = block.pause_ms / 1000.0

                    # Extend the last boundary's end so the subtitle stays
                    # visible throughout the silence, not just until the last
                    # spoken word.
                    if shifted:
                        shifted[-1] = {
                            **shifted[-1],
                            "end": round(shifted[-1]["end"] + silence_sec, 4),
                        }

                    silence_path = tmp / f"silence_{i:03d}.mp3"
                    _generate_silence(silence_path, silence_sec)
                    time_offset += silence_sec
                    segments.append(silence_path)

                    logger.debug(
                        "PauseInjector: {}ms {} pause after block {} | triggers: {}",
                        block.pause_ms,
                        block.pause_category.value,
                        i,
                        block.triggers,
                    )

                all_boundaries.extend(shifted)

            _concat_segments(segments, output_path)

        total_pause_ms = sum(b.pause_ms for b in blocks[:-1])
        logger.info(
            "PauseInjector: {} thought blocks | {}ms total silence | profile={}",
            len(blocks),
            total_pause_ms,
            profile,
        )

        return output_path, all_boundaries

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _synthesise_block(
        self,
        text: str,
        output_path: Path,
        optimizer,
        provider,
        *,
        style: str,
        language: str,
        scene_position: float,
        keywords: list[str] | None,
    ) -> tuple[Path, list[dict]]:
        """Optimise and synthesise one thought block. Returns (path, boundaries)."""
        optimized = optimizer.optimize(
            text,
            style=style,
            scene_position=scene_position,
            keywords=keywords,
        )
        _, boundaries = provider.generate_with_boundaries(
            text=optimized,
            output_path=output_path,
            language=language,
            style=style,
            scene_position=scene_position,
        )
        return output_path, boundaries

    def _fallback(
        self,
        narration: str,
        output_path: Path,
        optimizer,
        provider,
        *,
        style: str,
        language: str,
        scene_position: float,
        keywords: list[str] | None,
    ) -> tuple[Path, list[dict]]:
        """Plain synthesis — used when the analyzer returns no blocks."""
        optimized = optimizer.optimize(narration, style=style,
                                       scene_position=scene_position, keywords=keywords)
        _, boundaries = provider.generate_with_boundaries(
            text=optimized, output_path=output_path,
            language=language, style=style, scene_position=scene_position,
        )
        return output_path, boundaries
