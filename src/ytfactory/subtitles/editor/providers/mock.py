"""MockSubtitleEditor — deterministic no-API subtitle editor for tests.

Returns every cue unchanged with quality_score=100.
Use in tests to verify pipeline integration without live API calls.
"""

from __future__ import annotations

from ..provider import CueInput, CueOutput, EditResult, SubtitleEditorProvider


class MockSubtitleEditor(SubtitleEditorProvider):
    """Returns all cues unchanged, score=100, zero API calls."""

    def edit_cues(
        self,
        inputs: list[CueInput],
        *,
        pass_number: int = 1,
        retry_error: str | None = None,
        previous_score: int = 0,
        previous_failed_axes: list[str] | None = None,
    ) -> EditResult:
        return EditResult(
            outputs=[
                CueOutput(cue_id=inp.cue_id, text=inp.original_text) for inp in inputs
            ],
            quality_score=100,
            failed_axes=[],
            notes="",
            pass_number=pass_number,
        )
