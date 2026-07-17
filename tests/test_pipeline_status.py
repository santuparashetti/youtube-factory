"""Tests for ADR-0014: PipelineStatusWriter and ContextVar ambient context."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from ytfactory.shared.pipeline_status import (
    PipelineStatusWriter,
    activate_writer,
    get_writer,
    STAGE_LABELS,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def status_path(tmp_path: Path) -> Path:
    return tmp_path / "pipeline-status.json"


@pytest.fixture()
def writer(status_path: Path) -> PipelineStatusWriter:
    return PipelineStatusWriter("test-job-001", status_path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── ContextVar tests ──────────────────────────────────────────────────────────

def test_get_writer_returns_none_by_default():
    assert get_writer() is None


def test_activate_writer_installs_writer(writer):
    with activate_writer(writer):
        assert get_writer() is writer


def test_activate_writer_resets_on_exit(writer):
    with activate_writer(writer):
        pass
    assert get_writer() is None


def test_activate_writer_resets_on_exception(writer):
    with pytest.raises(ValueError):
        with activate_writer(writer):
            raise ValueError("boom")
    assert get_writer() is None


def test_activate_writer_is_reentrant_safe(tmp_path, writer):
    """Nested activate_writer restores the outer writer on exit."""
    writer2 = PipelineStatusWriter("job-2", tmp_path / "status2.json")
    with activate_writer(writer):
        assert get_writer() is writer
        with activate_writer(writer2):
            assert get_writer() is writer2
        assert get_writer() is writer
    assert get_writer() is None


def test_context_var_is_thread_isolated(tmp_path):
    """Two threads each see their own writer and neither leaks to the other."""
    path_a = tmp_path / "a.json"
    path_b = tmp_path / "b.json"
    writer_a = PipelineStatusWriter("job-a", path_a)
    writer_b = PipelineStatusWriter("job-b", path_b)

    seen: dict[str, str | None] = {}

    def run_a():
        with activate_writer(writer_a):
            import time; time.sleep(0.02)
            seen["a"] = get_writer()._status.job_id if get_writer() else None

    def run_b():
        with activate_writer(writer_b):
            import time; time.sleep(0.02)
            seen["b"] = get_writer()._status.job_id if get_writer() else None

    t1 = threading.Thread(target=run_a)
    t2 = threading.Thread(target=run_b)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert seen["a"] == "job-a"
    assert seen["b"] == "job-b"


# ── stage_start ───────────────────────────────────────────────────────────────

def test_stage_start_determinate(writer, status_path, capsys):
    writer.stage_start("image_generation", total=32)
    data = _read(status_path)
    assert data["current_stage"] == "image_generation"
    assert data["stage_state"] == "running"
    assert data["total"] == 32
    assert data["progress"] == 0
    out = capsys.readouterr().out
    assert "Image Generation" in out
    assert "0/32" in out


def test_stage_start_indeterminate(writer, status_path, capsys):
    writer.stage_start("scene_planning")
    data = _read(status_path)
    assert data["current_stage"] == "scene_planning"
    assert data["total"] == 0
    out = capsys.readouterr().out
    assert "Scene Planning" in out
    assert "..." in out


def test_stage_start_uses_message_override(writer, status_path):
    writer.stage_start("tts", total=10, message="custom msg")
    data = _read(status_path)
    assert data["message"] == "custom msg"


# ── stage_progress ────────────────────────────────────────────────────────────

def test_stage_progress_updates_counter(writer, status_path, capsys):
    writer.stage_start("tts", total=10)
    writer.stage_progress(5)
    data = _read(status_path)
    assert data["progress"] == 5
    assert data["message"] == "5/10"
    out = capsys.readouterr().out
    assert "5/10" in out


def test_stage_progress_without_total(writer, status_path):
    writer.stage_start("scene_planning")
    writer.stage_progress(3)
    data = _read(status_path)
    assert data["progress"] == 3
    assert data["message"] == "3"


# ── stage_retry ───────────────────────────────────────────────────────────────

def test_stage_retry_state_and_message(writer, status_path, capsys):
    writer.stage_start("documentary_enhancer_pass2")
    writer.stage_retry(1, 2, score=7.8)
    data = _read(status_path)
    assert data["stage_state"] == "retrying"
    assert data["retry_count"] == 1
    assert "7.8" in data["message"]
    assert "Retrying" in data["message"]


def test_stage_retry_no_score(writer, status_path):
    writer.stage_start("tts", total=5)
    writer.stage_retry(2, 3)
    data = _read(status_path)
    assert "2/3" in data["message"]
    assert "Score" not in data["message"]


def test_stage_retry_custom_message(writer, status_path):
    writer.stage_start("tts", total=5)
    writer.stage_retry(1, 2, message="custom retry msg")
    data = _read(status_path)
    assert data["message"] == "custom retry msg"


# ── stage_complete ────────────────────────────────────────────────────────────

def test_stage_complete_state_and_history(writer, status_path, capsys):
    writer.stage_start("image_generation", total=5)
    writer.stage_progress(5)
    writer.stage_complete()
    data = _read(status_path)
    assert data["stage_state"] == "completed"
    assert len(data["stages"]) == 1
    entry = data["stages"][0]
    assert entry["stage"] == "image_generation"
    assert entry["state"] == "completed"
    assert entry["elapsed_seconds"] >= 0.0
    out = capsys.readouterr().out
    assert "✓" in out
    assert "Image Generation" in out


def test_stage_complete_accumulates_history(writer, status_path):
    writer.stage_start("scene_planning")
    writer.stage_complete()
    writer.stage_start("image_generation", total=3)
    writer.stage_complete()
    data = _read(status_path)
    assert len(data["stages"]) == 2
    assert data["stages"][0]["stage"] == "scene_planning"
    assert data["stages"][1]["stage"] == "image_generation"


def test_stage_complete_records_elapsed(writer, status_path):
    import time
    writer.stage_start("tts", total=2)
    time.sleep(0.05)
    writer.stage_complete()
    data = _read(status_path)
    assert data["stages"][0]["elapsed_seconds"] >= 0.04


# ── stage_fail ────────────────────────────────────────────────────────────────

def test_stage_fail_state_and_error(writer, status_path, capsys):
    writer.stage_start("scene_rendering", total=10)
    writer.stage_fail("3 scenes failed to render")
    data = _read(status_path)
    assert data["stage_state"] == "failed"
    assert "3 scenes" in data["error"]
    assert data["stages"][0]["state"] == "failed"
    assert "3 scenes" in data["stages"][0]["error"]
    out = capsys.readouterr().out
    assert "✗" in out


def test_stage_fail_truncates_long_error(writer, status_path):
    long_error = "x" * 500
    writer.stage_start("scene_rendering", total=5)
    writer.stage_fail(long_error)
    data = _read(status_path)
    assert len(data["error"]) == 500          # full error in top-level field
    assert len(data["stages"][0]["error"]) <= 200  # truncated in history


# ── Atomic write ──────────────────────────────────────────────────────────────

def test_atomic_write_no_tmp_file_left(writer, status_path):
    writer.stage_start("tts", total=5)
    tmp = status_path.with_suffix(".tmp.json")
    assert not tmp.exists(), "temp file must be cleaned up after write"


def test_atomic_write_valid_json_always(writer, status_path):
    """The output file is always valid JSON even after multiple transitions."""
    writer.stage_start("tts", total=5)
    writer.stage_progress(2)
    writer.stage_retry(1, 2, score=7.0)
    writer.stage_complete()
    writer.stage_start("subtitle_generation", total=5)
    writer.stage_complete()
    data = _read(status_path)
    assert isinstance(data, dict)
    assert data["job_id"] == "test-job-001"


# ── JSON schema ───────────────────────────────────────────────────────────────

def test_status_json_has_all_required_fields(writer, status_path):
    writer.stage_start("image_generation", total=32)
    data = _read(status_path)
    required = {
        "job_id", "current_stage", "stage_state", "started_at", "updated_at",
        "elapsed_seconds", "retry_count", "progress", "total", "message",
        "error", "stages",
    }
    assert required <= data.keys()


def test_status_json_job_id_matches(writer, status_path):
    writer.stage_start("scene_planning")
    data = _read(status_path)
    assert data["job_id"] == "test-job-001"


def test_status_json_started_at_is_iso8601(writer, status_path):
    from datetime import datetime, timezone
    writer.stage_start("tts", total=5)
    data = _read(status_path)
    # Must parse as ISO-8601 UTC
    dt = datetime.fromisoformat(data["started_at"])
    assert dt.tzinfo is not None


# ── STAGE_LABELS coverage ─────────────────────────────────────────────────────

def test_stage_labels_cover_all_adr_stages():
    expected = {
        "research", "light_normalization", "documentary_enhancer_pass1",
        "documentary_enhancer_pass2", "scene_planning", "image_generation",
        "image_qa", "tts", "subtitle_generation", "subtitle_editing",
        "background_music", "scene_rendering", "video_merge", "cta_overlay",
        "final_packaging",
    }
    assert expected <= STAGE_LABELS.keys()


def test_unknown_stage_key_falls_back_gracefully(writer, status_path):
    writer.stage_start("unknown_custom_stage")
    data = _read(status_path)
    assert data["current_stage"] == "unknown_custom_stage"
    assert data["stage_state"] == "running"


# ── Full lifecycle simulation ─────────────────────────────────────────────────

def test_full_pipeline_lifecycle(tmp_path):
    path = tmp_path / "pipeline-status.json"
    w = PipelineStatusWriter("lifecycle-job", path)

    with activate_writer(w):
        _w = get_writer()
        assert _w is w

        _w.stage_start("scene_planning")
        _w.stage_complete()

        _w.stage_start("image_generation", total=3)
        for i in range(1, 4):
            _w.stage_progress(i)
        _w.stage_complete()

        _w.stage_start("documentary_enhancer_pass2")
        _w.stage_retry(1, 2, score=7.5)
        _w.stage_complete()

    data = _read(path)
    assert len(data["stages"]) == 3
    stages = [s["stage"] for s in data["stages"]]
    assert stages == ["scene_planning", "image_generation", "documentary_enhancer_pass2"]
    assert all(s["state"] == "completed" for s in data["stages"])
