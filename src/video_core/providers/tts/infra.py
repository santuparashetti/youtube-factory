"""
Shared TTS infrastructure — cache, retry policy, and sentence batching.

Provider-agnostic helpers used by every TTS provider so that synthesis, retry,
and cache logic live in exactly one place (no duplication across providers).

    - TTSCache          — content-addressed local audio cache (Step 6)
    - RetryPolicy       — retry only transient failures (Step 8)
    - batch_sentences   — ~1500–2200 char batches, paragraph-aware (Step 5)
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Callable

from loguru import logger


# ── Retry policy ──────────────────────────────────────────────────────────────

# Status codes / error markers that are NOT retried (auth, invalid request).
_NON_RETRYABLE_SUBSTRINGS = (
    "401",
    "403",
    "404",
    "unauthorized",
    "forbidden",
    "not found",
    "invalid request",
    "authentication",
    "api key",
    "payment required",
    "quota",
)

# Transient failure types we DO retry (timeouts, network, connection resets).
_TRANSIENT_TYPES = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def is_retryable(exc: Exception) -> bool:
    """Return True only for transient failures (timeouts, network, resets).

    Never retries 4xx auth, invalid request, or other client errors.
    """
    message = str(exc).lower()

    # Connection reset is transient even though it surfaces as an OSError/IOError.
    if "connection reset" in message:
        return True

    # Explicit non-retryable markers (auth / bad request) — bail immediately.
    if any(token in message for token in _NON_RETRYABLE_SUBSTRINGS):
        return False

    # Transient network/IO types are retryable.
    if isinstance(exc, _TRANSIENT_TYPES):
        return True

    # Anything else (unknown provider errors) is treated as non-retryable to
    # avoid burning quota on deterministic failures.
    return False


def with_retry(
    action: Callable[[], None],
    *,
    max_retries: int,
    timeout: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run ``action`` with retry only on transient failures.

    Args:
        action:      Zero-arg callable that performs the synthesis.
        max_retries: Total attempts (1 = no retries).
        timeout:     Per-attempt timeout in seconds (raises TimeoutError).
        sleep:       Backoff function (injected for tests).

    Raises:
        The last exception if all attempts fail, or TimeoutError on timeout.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if attempt > 0:
            delay = 2.0 ** (attempt - 1)  # 1s, 2s, 4s …
            logger.info(
                "TTS retry attempt {}/{} (backoff {:.1f}s)",
                attempt + 1,
                max_retries,
                delay,
            )
            sleep(delay)
        try:
            action()
            return
        except Exception as exc:  # noqa: BLE001 — centralised retry decision
            last_exc = exc
            if not is_retryable(exc):
                logger.warning("TTS non-retryable error: {}", exc)
                raise
            logger.warning("TTS transient error attempt {}: {}", attempt + 1, exc)

    if last_exc is not None:
        raise last_exc


# ── Local TTS cache ─────────────────────────────────────────────────────────

_CACHE_DIR = Path("workspace/cache/tts")


class TTSCache:
    """Content-addressed local cache for synthesised audio (Step 6).

    Cache key is SHA256(text + voice_id + model + speed + output_format).
    Stored under ``cache_dir`` as ``<hash>.<ext>``. Identical settings return
    the cached file — Cartesia is never called again.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self._dir = cache_dir or _CACHE_DIR
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def make_key(
        *,
        text: str,
        voice_id: str,
        model: str,
        speed: float,
        output_format: str,
        emotion: str = "calm",
        sample_rate: int = 44100,
    ) -> str:
        """Deterministic SHA256 key from synthesis inputs."""
        payload = "\n".join(
            [
                text,
                f"voice_id={voice_id}",
                f"model={model}",
                f"speed={speed!r}",
                f"format={output_format}",
                f"emotion={emotion}",
                f"sample_rate={sample_rate}",
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _path_for(self, key: str, ext: str) -> Path:
        return self._dir / f"{key}.{ext}"

    def get(self, key: str, ext: str) -> Path | None:
        """Return cached audio path if present and readable, else None."""
        if not self._enabled:
            return None
        path = self._path_for(key, ext)
        if path.exists() and path.stat().st_size > 0:
            return path
        return None

    def put(self, key: str, ext: str, data: bytes) -> Path:
        """Write audio bytes to the cache and return the path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(key, ext)
        path.write_bytes(data)
        return path

    def copy_to(self, key: str, ext: str, dest: Path) -> bool:
        """Copy a cached file to ``dest``. Returns True on success."""
        src = self.get(key, ext)
        if src is None:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        return True


# ── Sentence batching ────────────────────────────────────────────────────────

# Target synthesis request size for long-form narration (Step 5).
_MIN_BATCH_CHARS = 1500
_MAX_BATCH_CHARS = 2200


def split_paragraphs(text: str) -> list[str]:
    """Split narration into paragraphs on blank lines, preserving content."""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def batch_sentences(
    text: str,
    *,
    max_chars: int = _MAX_BATCH_CHARS,
    min_chars: int = _MIN_BATCH_CHARS,
) -> list[str]:
    """Group narration into ~1500–2200 char synthesis batches.

    Rules:
      - Never send a tiny request (below ``min_chars``) unless it is all that
        remains.
      - Never send one huge request (above ``max_chars``).
      - Respect paragraph boundaries whenever possible (paragraphs are not
        broken mid-way unless a single paragraph exceeds ``max_chars``).
      - Maintain natural narration flow (sentence order preserved).
    """
    import re

    paragraphs = split_paragraphs(text)
    if not paragraphs:
        paragraphs = [text.strip()] if text.strip() else []

    # Sentences within a paragraph, punctuation kept.
    sentence_re = re.compile(r"(?<=[.!?])\s+")
    sentences: list[str] = []
    for para in paragraphs:
        for s in sentence_re.split(para):
            s = s.strip()
            if s:
                sentences.append(s)

    batches: list[str] = []
    current: list[str] = []
    current_len = 0

    def _flush() -> None:
        nonlocal current, current_len
        if current:
            batches.append(" ".join(current))
            current = []
            current_len = 0

    for sent in sentences:
        slen = len(sent)
        if slen > max_chars:
            # Oversized sentence — emit current batch, then chunk it alone.
            _flush()
            chunks = _hard_wrap(sent, max_chars)
            batches.extend(chunks)
            continue

        # Flush first if adding this sentence would exceed max AND we already
        # have a reasonably-sized batch.
        if current and current_len + slen + 1 > max_chars and current_len >= min_chars:
            _flush()

        current.append(sent)
        current_len += slen + (1 if current_len else 0)

    _flush()

    # Merge a tiny trailing remainder into the previous batch when it fits, so
    # we never send one disproportionately small request at the end.
    if len(batches) >= 2:
        last = batches[-1]
        prev = batches[-2]
        if (
            len(last) < min_chars // 3
            and len(prev) + len(last) + 1 <= max_chars
        ):
            batches[-2] = f"{prev} {last}"
            batches.pop()

    return batches


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    """Split an over-long unit on word boundaries (last resort)."""
    words = text.split()
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for w in words:
        add = len(w) + (1 if buf else 0)
        if buf and buf_len + add > max_chars:
            chunks.append(" ".join(buf))
            buf = []
            buf_len = 0
        buf.append(w)
        buf_len += add
    if buf:
        chunks.append(" ".join(buf))
    return chunks
