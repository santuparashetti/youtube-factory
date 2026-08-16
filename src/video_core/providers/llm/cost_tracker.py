"""Thread-safe per-task LLM cost accumulator for a pipeline run."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class _CallRecord:
    task_label: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    call_count: int = 0


class CostTracker:
    """Singleton accumulator — records token usage per (task, model) across a run.

    Usage:
        CostTracker.reset()          # call at the start of each pipeline run
        CostTracker.record(...)      # called automatically by _TrackedProvider
        records = CostTracker.get_records()  # read back in the runner summary
    """

    _lock: threading.Lock = threading.Lock()
    _records: dict[tuple[str, str], _CallRecord] = {}

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._records = {}

    @classmethod
    def record(
        cls,
        task_label: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
    ) -> None:
        key = (task_label, model)
        with cls._lock:
            if key not in cls._records:
                cls._records[key] = _CallRecord(task_label=task_label, model=model)
            rec = cls._records[key]
            rec.input_tokens += input_tokens
            rec.output_tokens += output_tokens
            rec.cost_usd += cost_usd
            rec.call_count += 1

    @classmethod
    def get_records(cls) -> list[_CallRecord]:
        with cls._lock:
            return list(cls._records.values())

    @classmethod
    def has_data(cls) -> bool:
        with cls._lock:
            return bool(cls._records)
