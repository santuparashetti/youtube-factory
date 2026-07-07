"""SubtitleEditorProvider — abstract interface for subtitle editing backends.

Business logic (cue_id validation, retry-on-mismatch, scoring loop, debug
output) lives in SubtitleEditingEngine.  Providers only handle the LLM
call + JSON parsing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CueInput:
    cue_id: int
    start_time: str  # SRT format: HH:MM:SS,mmm (context for CPS awareness)
    end_time: str  # SRT format: HH:MM:SS,mmm
    duration_secs: float  # display window length in seconds
    cps: float  # current characters-per-second (diagnostic)
    original_text: str  # cue text; \n separates display lines


@dataclass
class CueOutput:
    cue_id: int
    text: str  # edited text; use \n for a two-line display break


@dataclass
class EditResult:
    outputs: list[CueOutput]  # one per input cue, cue_ids preserved
    quality_score: int  # LLM self-evaluated score 0–100
    failed_axes: list[str] = field(default_factory=list)
    notes: str = ""
    pass_number: int = 1


class SubtitleEditorProvider(ABC):
    """Interface for subtitle editing LLM providers.

    Implementors: LLMSubtitleEditor, MockSubtitleEditor.
    """

    @abstractmethod
    def edit_cues(
        self,
        inputs: list[CueInput],
        *,
        pass_number: int = 1,
        retry_error: str | None = None,
        previous_score: int = 0,
        previous_failed_axes: list[str] | None = None,
    ) -> EditResult:
        """Send cues to the backend for editorial improvement.

        Must return one CueOutput per input (same order, same cue_ids).
        Raises on hard backend failure (network, auth, parse error).
        """
        ...
