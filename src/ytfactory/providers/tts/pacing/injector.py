"""PauseInjector — orchestrates sentence-level TTS synthesis with explicit silence gaps.

Flow for each scene narration:

  1. SentenceAnalyzer splits narration into sentences and assigns pause_ms to each.
  2. For each sentence:
       a. SpeechOptimizer restructures the sentence into TTS-ready phrases.
       b. TTS provider synthesises the sentence → temp MP3 + word boundaries.
       c. Word boundaries are shifted by the cumulative time offset so far.
       d. A silence segment is appended (FFmpeg anullsrc) if pause_ms > 0.
  3. All audio segments are concatenated into the final output MP3.
  4. The master word-boundaries list (with correct absolute timestamps) is returned.

Downstream effects (automatic, no extra code needed):
  • Scene duration — VideoRenderer reads actual audio duration via ffprobe.
  • Subtitle timing — SubtitleEngine reads timing.json boundaries.
  • BGM mixing   — BGMMixer reads total video duration via ffprobe.
  • Motion       — zoompan runs for the full audio duration, no abrupt cuts.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

from .analyzer import SentenceAnalyzer


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

    Uses 24 kHz mono to match Edge TTS output format. Q:a 9 is the lowest
    (largest compression) — silence doesn't need audio quality headroom.
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
    """Orchestrates sentence-level TTS with contemplative silence gaps.

    Instantiate once at module level::

        _pacer = PauseInjector()

    Then call per scene::

        output_path, boundaries = _pacer.generate(
            narration, output_path, optimizer, provider, profile="spiritual", ...
        )
    """

    def __init__(self) -> None:
        self._analyzer = SentenceAnalyzer()

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
        """Synthesise *narration* with contemplative pauses and write to *output_path*.

        Returns ``(output_path, master_boundaries)`` where each boundary is
        ``{word, start, end}`` with timestamps already shifted to account for
        inserted silence segments.
        """
        sentences = self._analyzer.analyze(narration, profile)

        if not sentences:
            logger.warning("PauseInjector: no sentences found — falling back to plain synthesis")
            return self._fallback(narration, output_path, optimizer, provider,
                                  style=style, language=language,
                                  scene_position=scene_position, keywords=keywords)

        # Single-sentence scenes don't need inter-sentence pauses.
        # Still run through the optimizer so prosody is applied correctly.
        if len(sentences) == 1:
            return self._synthesise_sentence(
                sentences[0].text, output_path, optimizer, provider,
                style=style, language=language,
                scene_position=scene_position, keywords=keywords,
            )

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            segments: list[Path] = []
            all_boundaries: list[dict] = []
            time_offset = 0.0

            for i, sentence in enumerate(sentences):
                sent_audio = tmp / f"sent_{i:03d}.mp3"

                _, sent_boundaries = self._synthesise_sentence(
                    sentence.text, sent_audio, optimizer, provider,
                    style=style, language=language,
                    scene_position=scene_position, keywords=keywords,
                )

                # Shift this sentence's word boundaries by the cumulative offset.
                for b in sent_boundaries:
                    all_boundaries.append({
                        "word": b["word"],
                        "start": round(b["start"] + time_offset, 4),
                        "end": round(b["end"] + time_offset, 4),
                    })

                audio_dur = _probe_duration(sent_audio)
                time_offset += audio_dur
                segments.append(sent_audio)

                # Insert silence after every sentence except the last.
                is_last = i == len(sentences) - 1
                if not is_last and sentence.pause_ms > 0:
                    silence_sec = sentence.pause_ms / 1000.0
                    silence_path = tmp / f"silence_{i:03d}.mp3"
                    _generate_silence(silence_path, silence_sec)
                    time_offset += silence_sec
                    segments.append(silence_path)

                    logger.debug(
                        "PauseInjector: {}ms {} pause after sentence {} | triggers: {}",
                        sentence.pause_ms,
                        sentence.pause_category,
                        i,
                        sentence.triggers,
                    )

            _concat_segments(segments, output_path)

        total_pause_ms = sum(s.pause_ms for s in sentences[:-1])
        logger.info(
            "PauseInjector: {} sentences | {}ms total pauses | profile={}",
            len(sentences),
            total_pause_ms,
            profile,
        )

        return output_path, all_boundaries

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _synthesise_sentence(
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
        """Optimise and synthesise a single sentence. Returns (path, boundaries)."""
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
        """Plain synthesis path — used when analyzer returns no sentences."""
        optimized = optimizer.optimize(narration, style=style,
                                       scene_position=scene_position, keywords=keywords)
        _, boundaries = provider.generate_with_boundaries(
            text=optimized, output_path=output_path,
            language=language, style=style, scene_position=scene_position,
        )
        return output_path, boundaries
