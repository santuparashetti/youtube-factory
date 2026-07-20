"""ADR-0014: Pipeline Progress Reporting & Status Tracking.

Single source of truth for pipeline progress — writes pipeline-status.json
atomically on every transition and streams stage summaries to the terminal.

Usage (from BuildPipeline or any orchestrator)::

    writer = PipelineStatusWriter(project_id, project_dir / "pipeline-status.json")
    with activate_writer(writer):
        images_pipeline.run(project_id)
        voice_pipeline.run(project_id)
        ...

Usage (inside a pipeline)::

    from ytfactory.shared.pipeline_status import get_writer

    _w = get_writer()
    if _w:
        _w.stage_start("image_generation", total=32)
    for i, scene in enumerate(scenes, 1):
        ...
        if _w:
            _w.stage_progress(i)
    if _w:
        _w.stage_complete()

When no writer is active (``get_writer()`` returns None) every pipeline
falls back to its existing console output — backward-compatible.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from rich.console import Console

_console = Console()

_current_writer: ContextVar[PipelineStatusWriter | None] = ContextVar(
    "pipeline_status_writer", default=None
)

# Human-readable labels for every stage defined in the ADR.
STAGE_LABELS: dict[str, str] = {
    "research": "Research",
    "light_normalization": "Light Normalization",
    "documentary_enhancer_pass1": "Documentary Enhancer — Pass 1",
    "documentary_enhancer_pass2": "Documentary Enhancer — Pass 2",
    "scene_planning": "Scene Planning",
    "image_generation": "Image Generation",
    "image_qa": "Image QA",
    "tts": "TTS",
    "subtitle_generation": "Subtitle Generation",
    "subtitle_editing": "Subtitle Editing",
    "background_music": "Background Music",
    "scene_rendering": "Scene Rendering",
    "video_merge": "Video Merge",
    "cta_overlay": "CTA Overlay",
    "final_packaging": "Final Packaging",
}


class PipelineAbort(Exception):
    """Raised when a critical quality gate fails and the pipeline must halt.

    Carries the failing stage name and a human-readable reason so callers can
    produce a concise abort summary without inspecting inner exceptions.
    """

    def __init__(self, stage: str, reason: str) -> None:
        self.stage = stage
        self.reason = reason
        super().__init__(f"Pipeline aborted at stage '{stage}': {reason}")


def get_writer() -> PipelineStatusWriter | None:
    """Return the PipelineStatusWriter active in the current context, or None."""
    return _current_writer.get()


@contextmanager
def activate_writer(
    writer: PipelineStatusWriter,
) -> Generator[PipelineStatusWriter, None, None]:
    """Context manager that installs *writer* as the ambient pipeline status writer.

    Uses ``ContextVar`` so the writer is isolated per async task / thread and
    is safely reset when the context exits (even on exception).
    """
    token = _current_writer.set(writer)
    try:
        yield writer
    finally:
        _current_writer.reset(token)


@dataclass
class PipelineStatus:
    """In-memory mirror of the fields written to pipeline-status.json."""

    job_id: str
    current_stage: str = ""
    stage_state: str = "pending"
    started_at: str = ""
    updated_at: str = ""
    elapsed_seconds: float = 0.0
    retry_count: int = 0
    progress: int = 0
    total: int = 0
    message: str = ""
    error: str = ""
    stages: list[dict] = field(default_factory=list)


class PipelineStatusWriter:
    """Write pipeline-status.json and stream stage transitions to the terminal.

    Stage states
    ------------
    pending   — not yet started (initial)
    running   — in progress
    retrying  — validation failed; another attempt is beginning
    completed — done successfully
    failed    — unrecoverable error

    Progress types
    --------------
    Determinate  — call ``stage_start(stage, total=N)`` then
                   ``stage_progress(i)`` for each item.
    Indeterminate — call ``stage_start(stage)`` (no total).
    Iterative    — call ``stage_retry(attempt, max_attempts, score=s)``
                   inside the retry loop.
    """

    def __init__(self, job_id: str, output_path: Path) -> None:
        self._status = PipelineStatus(job_id=job_id)
        self._path = output_path
        self._stage_started_at: float = 0.0
        self._in_progress_line: bool = False

    # ── Public API ────────────────────────────────────────────────────────

    def stage_start(self, stage: str, total: int = 0, message: str = "") -> None:
        """Mark *stage* as running.

        Parameters
        ----------
        stage:   One of the stage keys in ``STAGE_LABELS``.
        total:   Expected item count for determinate progress (0 = indeterminate).
        message: Optional free-text message written to the status file.
        """
        label = _label(stage)
        self._stage_started_at = time.monotonic()
        self._status.current_stage = stage
        self._status.stage_state = "running"
        self._status.progress = 0
        self._status.total = total
        self._status.retry_count = 0
        self._status.error = ""
        self._status.message = message or (f"0/{total}" if total else "running")
        self._in_progress_line = False

        if total > 0:
            sys.stdout.write(f"  ▶ {label} 0/{total}")
        else:
            sys.stdout.write(f"  ⟳ {label}...")
        sys.stdout.flush()
        self._in_progress_line = True
        self._write()

    def stage_progress(self, progress: int, message: str = "") -> None:
        """Update the progress counter for a running determinate stage."""
        label = _label(self._status.current_stage)
        self._status.progress = progress
        self._status.elapsed_seconds = time.monotonic() - self._stage_started_at
        total = self._status.total
        self._status.message = message or (f"{progress}/{total}" if total else str(progress))

        if total:
            sys.stdout.write(f"\r  ▶ {label} {progress}/{total}")
        else:
            sys.stdout.write(f"\r  ▶ {label} {progress}")
        sys.stdout.flush()
        self._in_progress_line = True
        self._write()

    def stage_retry(
        self,
        attempt: int,
        max_attempts: int,
        score: float | None = None,
        message: str = "",
    ) -> None:
        """Record that a retry is starting for the current stage.

        Parameters
        ----------
        attempt:      Current attempt number (1-based).
        max_attempts: Total allowed attempts.
        score:        Optional quality score that triggered the retry.
        message:      Override message; auto-built from attempt/score when omitted.
        """
        label = _label(self._status.current_stage)
        score_part = f" Score: {score:.1f}/10" if score is not None else ""
        retry_msg = message or f"Attempt {attempt}/{max_attempts}{score_part} — Retrying..."
        self._status.stage_state = "retrying"
        self._status.retry_count = attempt
        self._status.elapsed_seconds = time.monotonic() - self._stage_started_at
        self._status.message = retry_msg

        self._flush_progress_line()
        _console.print(f"  [bold yellow]⟳[/bold yellow] {label} {retry_msg}")
        self._write()

    def stage_complete(self, message: str = "") -> None:
        """Mark the current stage as successfully completed."""
        elapsed = time.monotonic() - self._stage_started_at
        label = _label(self._status.current_stage)
        self._status.stage_state = "completed"
        self._status.elapsed_seconds = elapsed
        self._status.message = message or "done"
        self._status.stages.append(
            {
                "stage": self._status.current_stage,
                "label": label,
                "state": "completed",
                "elapsed_seconds": round(elapsed, 2),
            }
        )

        self._flush_progress_line()
        _console.print(f"  [bold green]✓[/bold green] {label}")
        self._write()

    def stage_fail(self, error: str) -> None:
        """Mark the current stage as failed and record *error*."""
        elapsed = time.monotonic() - self._stage_started_at
        label = _label(self._status.current_stage)
        self._status.stage_state = "failed"
        self._status.error = error
        self._status.elapsed_seconds = elapsed
        self._status.stages.append(
            {
                "stage": self._status.current_stage,
                "label": label,
                "state": "failed",
                "elapsed_seconds": round(elapsed, 2),
                "error": error[:200],
            }
        )

        self._flush_progress_line()
        _console.print(f"  [bold red]✗[/bold red] {label}: {error[:120]}")
        self._write()

    # ── Internal ──────────────────────────────────────────────────────────

    def _flush_progress_line(self) -> None:
        if self._in_progress_line:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_progress_line = False

    def _write(self) -> None:
        """Atomically write pipeline-status.json (tmp → rename)."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._status.updated_at = now
        if not self._status.started_at:
            self._status.started_at = now

        data: dict = {
            "job_id": self._status.job_id,
            "current_stage": self._status.current_stage,
            "stage_state": self._status.stage_state,
            "started_at": self._status.started_at,
            "updated_at": self._status.updated_at,
            "elapsed_seconds": round(self._status.elapsed_seconds, 2),
            "retry_count": self._status.retry_count,
            "progress": self._status.progress,
            "total": self._status.total,
            "message": self._status.message,
            "error": self._status.error,
            "stages": self._status.stages,
        }

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _label(stage: str) -> str:
    return STAGE_LABELS.get(stage, stage.replace("_", " ").title())
