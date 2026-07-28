"""YouTube ingestion chain — alternate Phase 1 source: a YouTube URL instead
of a pre-written script file or AI research.

Three stages, each independently resumable (skips its own work when its
output artifact already exists on disk):
  AudioAcquisitionPipeline — yt-dlp download, cached by URL
  TranscriptionPipeline    — WhisperX ASR (source language, e.g. Kannada)
  TranslationPipeline      — one LLM call, ATMA_DISCOURSE_TO_BASE_SCRIPT.md
                              as system prompt -> English base script

Artifacts (workspace/jobs/<project-id>/ingestion/):
  source.json        — {"url": ...} — cache key for the audio download
  audio.mp3           — downloaded audio track
  transcript_kn.md    — WhisperX transcript (source language)
  base_script_en.md   — LLM-translated English base script

The English base script is also written to script/script.md — the same
canonical location a pre-written or imported script would occupy — so
human_review_base_script_node and script_enhancer find it identically.
"""

from __future__ import annotations

import functools
import json
import subprocess
from pathlib import Path

from loguru import logger
from rich.console import Console

from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from video_core.providers.llm.factory import get_llm_provider

console = Console()

_TRANSLATION_SYSTEM_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "script_enhancer"
    / "prompts"
    / "ATMA_DISCOURSE_TO_BASE_SCRIPT.md"
)


@functools.lru_cache(maxsize=1)
def _load_translation_system_prompt() -> str:
    return _TRANSLATION_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()


def _ingest_dir(project_id: str) -> Path:
    d = Path(WORKSPACE_DIR) / project_id / "ingestion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _download_audio(url: str, out_path: Path) -> None:
    """Download a YouTube video's audio track as mp3 via yt-dlp.

    Adapted from base_scripts/download_audio.py — same yt-dlp invocation,
    targeting a caller-specified exact output path instead of a data/ folder.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stem = out_path.with_suffix("")
    try:
        subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "mp3", "-o", f"{stem}.%(ext)s", url],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "yt-dlp not found. Install with: pip install -U yt-dlp"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"yt-dlp failed for {url}: {exc.stderr or exc.stdout or 'unknown error'}"
        ) from exc
    if not out_path.exists():
        raise RuntimeError(f"yt-dlp did not produce the expected output: {out_path}")


def _transcribe(audio_path: Path, *, language: str, model_name: str, device: str) -> str:
    """WhisperX ASR transcription (full transcribe, not forced alignment).

    Distinct from voice/aligner.py's align() — that takes KNOWN text and finds
    timing; this takes ONLY audio and produces text via a Whisper ASR model.
    """
    try:
        import whisperx  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "YouTube ingest transcription requires the 'whisperx' package. "
            "Install with: pip install whisperx\n"
            f"Original error: {exc}"
        ) from exc

    compute_type = "float32" if device == "cpu" else "float16"
    logger.info(
        "YouTube ingest: transcribing {} (language={}, model={}, device={})",
        audio_path.name,
        language,
        model_name,
        device,
    )
    model = whisperx.load_model(model_name, device, compute_type=compute_type, language=language)
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, language=language)

    segments = result.get("segments", [])
    text = " ".join(seg.get("text", "").strip() for seg in segments if seg.get("text"))
    return text.strip()


class AudioAcquisitionPipeline:
    """Download a YouTube video's audio track, cached by URL."""

    def run(self, project_id: str, url: str) -> Path:
        ingest_dir = _ingest_dir(project_id)
        audio_path = ingest_dir / "audio.mp3"
        source_file = ingest_dir / "source.json"

        cached_url = None
        if source_file.exists():
            try:
                cached_url = json.loads(source_file.read_text(encoding="utf-8")).get("url")
            except (json.JSONDecodeError, OSError):
                cached_url = None

        if audio_path.exists() and cached_url == url:
            logger.info("YouTube ingest: audio cached, skipping download ({})", audio_path)
            console.print(f"  [dim]Audio cached — skipping download: {audio_path}[/dim]")
            return audio_path

        console.print(f"\n[bold magenta]🎧 Acquiring audio[/bold magenta] — {url}")
        _download_audio(url, audio_path)
        source_file.write_text(json.dumps({"url": url}, indent=2), encoding="utf-8")
        console.print(f"  [green]✓[/green] Audio downloaded: {audio_path}")
        return audio_path


class TranscriptionPipeline:
    """WhisperX ASR transcription of the acquired audio."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def run(self, project_id: str) -> str:
        ingest_dir = _ingest_dir(project_id)
        transcript_path = ingest_dir / "transcript_kn.md"
        audio_path = ingest_dir / "audio.mp3"

        if transcript_path.exists():
            logger.info(
                "YouTube ingest: transcript cached, skipping transcription ({})",
                transcript_path,
            )
            console.print(
                f"  [dim]Transcript cached — skipping transcription: {transcript_path}[/dim]"
            )
            return transcript_path.read_text(encoding="utf-8")

        if not audio_path.exists():
            raise FileNotFoundError(
                f"TranscriptionPipeline: no audio found at {audio_path} — "
                "run audio acquisition first"
            )

        language = self._settings.youtube_ingest_language
        console.print(
            f"\n[bold magenta]📝 Transcribing audio[/bold magenta] — "
            f"language={language}, model={self._settings.whisperx_model}..."
        )
        transcript = _transcribe(
            audio_path,
            language=language,
            model_name=self._settings.whisperx_model,
            device=self._settings.whisperx_device,
        )
        transcript_path.write_text(transcript, encoding="utf-8")
        console.print(
            f"  [green]✓[/green] Transcript written: {transcript_path} "
            f"({len(transcript.split())} words)"
        )
        return transcript


class TranslationPipeline:
    """Translate the source-language transcript into an English base script.

    A single LLM call using ATMA_DISCOURSE_TO_BASE_SCRIPT.md as the system
    prompt. Output is faithful, complete, un-styled clay — script_enhancer
    (Pass 1/2) and the Structural Retention Pass do the documentary styling.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._llm = get_llm_provider(settings)

    def run(self, project_id: str) -> str:
        ingest_dir = _ingest_dir(project_id)
        base_script_path = ingest_dir / "base_script_en.md"
        transcript_path = ingest_dir / "transcript_kn.md"

        if base_script_path.exists():
            logger.info(
                "YouTube ingest: base script cached, skipping translation ({})",
                base_script_path,
            )
            console.print(
                f"  [dim]Base script cached — skipping translation: {base_script_path}[/dim]"
            )
            base_script = base_script_path.read_text(encoding="utf-8")
        else:
            if not transcript_path.exists():
                raise FileNotFoundError(
                    f"TranslationPipeline: no transcript found at {transcript_path} — "
                    "run transcription first"
                )
            transcript = transcript_path.read_text(encoding="utf-8")

            console.print("\n[bold magenta]🌐 Translating to English base script[/bold magenta]...")
            response = self._llm.generate(
                f"TRANSCRIPT:\n{transcript}",
                system_prompt=_load_translation_system_prompt(),
                temperature=0.3,
            )
            base_script = response.text.strip()
            base_script_path.write_text(base_script, encoding="utf-8")
            console.print(
                f"  [green]✓[/green] Base script written: {base_script_path} "
                f"({len(base_script.split())} words)"
            )

        # Canonical location — same file a pre-written/imported script occupies.
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        (script_dir / "script.md").write_text(base_script, encoding="utf-8")

        return base_script
