"""
Cartesia TTS provider — premium cloud narration (Step 3).

Uses the official Cartesia Python SDK. Optimised for long-form documentary /
spiritual narration:

  - Batch synthesis into ~1500–2200 char requests (Step 5) to minimise API
    calls while keeping prosody natural.
  - Local content-addressed cache (Step 6) — identical settings never re-call
    Cartesia.
  - Retry only on transient failures (Step 8) — never on 401/403/404.
  - Fail-fast validation of required config (Step 9) at construction.
  - Structured logging before/after synthesis (Step 7).

The provider consumes a VoiceProfile (provider-agnostic) resolved from the
pipeline, but falls back to raw SharedSettings fields if a profile is absent.
"""

from __future__ import annotations

import time
from pathlib import Path

from loguru import logger

from video_core.config.shared_settings import SharedSettings

from .base import TTSProvider
from .capabilities import ProviderCapabilities
from .infra import TTSCache, batch_sentences, with_retry
from .voice_profiles import VoiceProfile


class CartesiaTTSProvider(TTSProvider):
    """Premium cloud TTS via Cartesia (sonic-3.5 / sonic-3)."""

    def __init__(
        self,
        settings: SharedSettings,
        *,
        profile: VoiceProfile | None = None,
        cache: TTSCache | None = None,
    ) -> None:
        self._settings = settings

        # Fail-fast: required configuration must be present (Step 9).
        if not settings.cartesia_api_key:
            raise ValueError(
                "Cartesia TTS requires CARTESIA_API_KEY — set it in .env"
            )
        if not settings.cartesia_model:
            raise ValueError(
                "Cartesia TTS requires CARTESIA_MODEL — set it in .env"
            )

        # Voice ID comes from the VoiceProfile (preferred) or raw setting.
        voice_id = ""
        speed = settings.cartesia_speed
        if profile is not None and profile.provider == "cartesia":
            voice_id = profile.voice or settings.cartesia_voice_id
            speed = profile.speed or settings.cartesia_speed
        else:
            voice_id = settings.cartesia_voice_id

        if not voice_id:
            raise ValueError(
                "Cartesia TTS requires CARTESIA_VOICE_ID — set it in .env"
            )

        self._voice_id = voice_id
        self._speed = speed
        self._model = settings.cartesia_model
        self._output_format = settings.cartesia_output_format or "wav"
        self._timeout = settings.cartesia_timeout
        self._max_chars = settings.cartesia_max_chars
        self._sample_rate = settings.cartesia_sample_rate
        self._emotion = settings.cartesia_emotion or "calm"
        self._pronunciation_dict_id = settings.cartesia_pronunciation_dict_id or ""

        self._cache = cache or TTSCache(
            enabled=settings.cartesia_cache_enabled
        )
        self._client = None  # lazy-loaded

    # ── Capabilities ──────────────────────────────────────────────────────────

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="cartesia",
            supports_ssml=False,
            supports_word_boundaries=False,  # via WhisperX alignment instead
            supports_pitch=False,
            supports_rate=True,  # speed via generation_config
            supports_streaming=True,  # SDK streams audio chunks
            supports_emotion=True,  # generation_config.emotion
            supports_voice_styles=False,
        )

    # ── Lazy client ────────────────────────────────────────────────────────────

    def _get_client(self):
        """Lazily construct the Cartesia client (heavy httpx import)."""
        if self._client is None:
            try:
                from cartesia import Cartesia  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "Cartesia TTS requires the 'cartesia' package. "
                    "Install it with: pip install cartesia\n"
                    f"Original error: {exc}"
                ) from exc
            self._client = Cartesia(api_key=self._settings.cartesia_api_key)
        return self._client

    # ── Internal synthesis ─────────────────────────────────────────────────────

    def _synthesise_chunk(self, text: str, output_path: Path) -> float:
        """Synthesise one text batch to ``output_path``. Returns duration (s).

        Uses the local cache first (Step 6); otherwise calls Cartesia and
        stores the result. Returns audio duration via ffprobe.
        """
        ext = self._output_format
        key = TTSCache.make_key(
            text=text,
            voice_id=self._voice_id,
            model=self._model,
            speed=self._speed,
            output_format=ext,
        )

        # Cache hit (Step 6) — never call Cartesia again.
        if self._cache.copy_to(key, ext, output_path):
            logger.debug(
                "TTS [cartesia] cache HIT — skipping API call (chars={})",
                len(text),
            )
            return self._probe_duration(output_path)

        client = self._get_client()

        output_path.parent.mkdir(parents=True, exist_ok=True)

        def _call() -> bytes:
            chunks: list[bytes] = []
            response = client.tts.bytes(
                model_id=self._model,
                transcript=text,
                voice={"mode": "id", "id": self._voice_id},
                language="en",
                output_format={
                    "container": self._output_format,
                    "sample_rate": self._sample_rate,
                    "encoding": "pcm_s16le" if self._output_format == "wav" else None,
                },
                speed=(
                    "slow"
                    if self._speed < 0.9
                    else "normal"
                    if self._speed <= 1.1
                    else "fast"
                ),
                generation_config={
                    "speed": self._speed,
                    "emotion": self._emotion,
                },
                pronunciation_dict_id=(
                    self._pronunciation_dict_id or None
                ),
            )
            for chunk in response:
                chunks.append(chunk)
            return b"".join(chunks)

        def _action() -> None:
            audio = _call_with_timeout(_call, self._timeout)
            # Persist to cache and write to output.
            if self._cache.enabled:
                self._cache.put(key, ext, audio)
            output_path.write_bytes(audio)

        # Retry only transient failures (Step 8).
        max_retries = (
            self._settings.tts_max_retries if self._settings.tts_auto_retry else 1
        )
        with_retry(_action, max_retries=max_retries, timeout=self._timeout)

        return self._probe_duration(output_path)

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
        scene_position: float = 0.5,
    ) -> Path:
        resolved_voice = voice or self._voice_id
        batches = batch_sentences(text, max_chars=self._max_chars)

        logger.info(
            "TTS [cartesia] model={} voice={} chars={} format={} cache_hit={}",
            self._model,
            resolved_voice,
            len(text),
            self._output_format,
            "pending",
        )

        t0 = time.perf_counter()
        if len(batches) == 1:
            duration = self._synthesise_chunk(batches[0], output_path)
        else:
            duration = self._synthesize_batched(batches, output_path)
        elapsed = time.perf_counter() - t0

        logger.info(
            "TTS [cartesia] latency={:.1f}s duration={:.2f}s provider=cartesia",
            elapsed,
            duration,
        )
        return output_path

    def _synthesize_batched(
        self, batches: list[str], output_path: Path
    ) -> float:
        """Synthesise multiple batches and concatenate into one file."""
        from .validator import _ffprobe_duration

        tmp_paths: list[Path] = []
        total = 0.0
        try:
            for i, batch in enumerate(batches):
                tmp = output_path.with_suffix(f".part{i}{output_path.suffix}")
                tmp_paths.append(tmp)
                total += self._synthesise_chunk(batch, tmp)
            # Concatenate parts with FFmpeg (handles wav/mp3 uniformly).
            _concat_audio(tmp_paths, output_path)
        finally:
            for p in tmp_paths:
                p.unlink(missing_ok=True)
        return _ffprobe_duration(output_path) or total

    def generate_with_boundaries(
        self,
        text: str,
        output_path: Path,
        *,
        voice: str | None = None,
        language: str = "en",
        style: str | None = None,
        scene_position: float = 0.5,
    ) -> tuple[Path, list[dict]]:
        """Generate audio. Returns empty boundaries — use WhisperX for timing."""
        audio_path = self.generate(
            text,
            output_path,
            voice=voice,
            language=language,
            style=style,
            scene_position=scene_position,
        )
        return audio_path, []

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _probe_duration(path: Path) -> float:
        from .validator import _ffprobe_duration

        return _ffprobe_duration(path)


def _call_with_timeout(func, timeout: float) -> bytes:
    """Run ``func`` in a thread with a hard timeout (raises TimeoutError)."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(func)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError(
                f"Cartesia synthesis timed out after {timeout}s"
            ) from exc


def _concat_audio(parts: list[Path], output_path: Path) -> None:
    """Concatenate audio files into ``output_path`` via FFmpeg."""
    import subprocess

    # Use the concat demuxer for robust WAV/MP3 joining.
    list_file = output_path.with_suffix(".concat.txt")
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
    finally:
        list_file.unlink(missing_ok=True)
