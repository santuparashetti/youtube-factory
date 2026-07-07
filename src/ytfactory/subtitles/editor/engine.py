"""SubtitleEditingEngine — document-first LLM subtitle editing with quality loop.

Implements the full V2 spec:
  - Single LLM call per scene (document-first editing)
  - 1:1 cue_id validation + retry-on-mismatch (up to max_retries)
  - Quality scoring loop (up to max_passes, pass threshold 95)
  - Fallback to best-scoring version with BEST EFFORT label
  - Debug file generation: {scene-id}-original.srt, -edited.srt, -diff.md
  - Word-level integrity enforcement (never change actual words)
"""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from ytfactory.subtitles.models import SubtitleCue

from .provider import CueInput, CueOutput, EditResult, SubtitleEditorProvider


def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _words(text: str) -> list[str]:
    """Extract normalised word tokens for word-integrity comparison."""
    return re.findall(r"[a-zA-Z0-9']+", text.lower())


class SubtitleEditingEngine:
    """Orchestrate the V2 subtitle editing pipeline.

    Calls the provider up to max_passes times; keeps the highest-scoring
    valid edit.  All cue_id / count / word-integrity enforcement happens
    here — providers only handle the LLM call and JSON parsing.
    """

    def __init__(
        self,
        provider: SubtitleEditorProvider,
        *,
        max_passes: int = 3,
        pass_threshold: float = 95.0,
        max_retries: int = 3,
        debug: bool = False,
    ) -> None:
        self._provider = provider
        self._max_passes = max_passes
        self._pass_threshold = pass_threshold
        self._max_retries = max_retries
        self._debug = debug

    # ── Public API ─────────────────────────────────────────────────────────

    def edit(
        self,
        cues: list[SubtitleCue],
        scene_id: str,
        project_id: str,
    ) -> list[SubtitleCue]:
        """Edit subtitle cues and return the best improved version.

        Returns the original cues if no valid edit could be produced.
        """
        if not cues:
            return cues

        # Freeze the true originals for word-integrity validation across all passes
        true_originals = ["\n".join(c.lines) for c in cues]

        # working_cues advances with every pass (each pass builds on the previous)
        # best_cues tracks the highest-scoring version for final output
        working_cues: list[SubtitleCue] = cues
        best_cues: list[SubtitleCue] = cues
        best_score = 0
        best_effort = False
        last_result: EditResult | None = None

        for pass_num in range(1, self._max_passes + 1):
            inputs = self._build_inputs(working_cues)
            result = self._try_edit(
                inputs,
                pass_num=pass_num,
                previous_score=best_score,
                previous_failed_axes=last_result.failed_axes if last_result else [],
            )

            if result is None:
                logger.warning(
                    "Subtitle editor [{}]: pass {} — all retries exhausted, keeping best so far",
                    scene_id,
                    pass_num,
                )
                break

            # Word-level integrity check — revert any cue whose words changed
            # (always compare against the TRUE original TTS text, not the working copy)
            validated_outputs = self._validate_word_integrity(
                inputs, result.outputs, true_originals
            )

            # Apply the validated edits to fresh SubtitleCue objects
            edited_cues = self._apply_edits(cues, validated_outputs)
            score = result.quality_score
            last_result = result

            logger.debug(
                "Subtitle editor [{}]: pass {}/{} → score={}/100 failed={}",
                scene_id,
                pass_num,
                self._max_passes,
                score,
                result.failed_axes,
            )

            # Always advance the working state (iterative refinement)
            working_cues = edited_cues

            # Track the best-scoring version for final output
            if score > best_score:
                best_score = score
                best_cues = edited_cues

            if score >= self._pass_threshold:
                logger.debug("Subtitle editor [{}]: PASS (score={})", scene_id, score)
                break
        else:
            if best_score < self._pass_threshold:
                best_effort = True
                logger.warning(
                    "Subtitle editor [{}]: BEST EFFORT — max passes exhausted, "
                    "best score={}/100",
                    scene_id,
                    best_score,
                )

        if best_effort:
            logger.info(
                "Subtitle editor [{}]: outputting best-effort result (score={})",
                scene_id,
                best_score,
            )

        if self._debug:
            self._write_debug(scene_id, project_id, cues, best_cues)

        return best_cues

    # ── Internal helpers ────────────────────────────────────────────────────

    def _try_edit(
        self,
        inputs: list[CueInput],
        *,
        pass_num: int,
        previous_score: int,
        previous_failed_axes: list[str],
    ) -> EditResult | None:
        """Call provider with retry-on-cue_id-mismatch; return None on exhaustion."""
        retry_error: str | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                result = self._provider.edit_cues(
                    inputs,
                    pass_number=pass_num,
                    retry_error=retry_error,
                    previous_score=previous_score,
                    previous_failed_axes=previous_failed_axes,
                )
            except Exception as exc:
                retry_error = f"Provider error: {exc}"
                logger.warning(
                    "Subtitle editor: provider error on attempt {}/{}: {}",
                    attempt,
                    self._max_retries,
                    exc,
                )
                continue

            # Validate count
            if len(result.outputs) != len(inputs):
                retry_error = f"Wrong cue count: expected {len(inputs)}, got {len(result.outputs)}."
                logger.warning(
                    "Subtitle editor: wrong count on attempt {}/{}: {}",
                    attempt,
                    self._max_retries,
                    retry_error,
                )
                continue

            # Validate 1:1 cue_id coverage
            input_ids = {inp.cue_id for inp in inputs}
            output_ids = {out.cue_id for out in result.outputs}
            if input_ids != output_ids:
                missing = sorted(input_ids - output_ids)
                extra = sorted(output_ids - input_ids)
                retry_error = (
                    f"cue_id mismatch — missing: {missing}, extra: {extra}. "
                    f"Every input cue_id must appear exactly once in the output."
                )
                logger.warning(
                    "Subtitle editor: cue_id mismatch on attempt {}/{}: {}",
                    attempt,
                    self._max_retries,
                    retry_error,
                )
                continue

            return result  # valid structure

        return None

    def _validate_word_integrity(
        self,
        inputs: list[CueInput],
        outputs: list[CueOutput],
        true_originals: list[str],
    ) -> list[CueOutput]:
        """Revert any cue whose word sequence changed from the true original."""
        output_map = {out.cue_id: out for out in outputs}
        validated: list[CueOutput] = []

        for inp, orig_text in zip(inputs, true_originals):
            out = output_map.get(inp.cue_id)
            if out is None:
                validated.append(CueOutput(cue_id=inp.cue_id, text=orig_text))
                continue

            if _words(orig_text) != _words(out.text):
                logger.warning(
                    "Subtitle editor: word mismatch on cue {} — reverting to original",
                    inp.cue_id,
                )
                validated.append(CueOutput(cue_id=inp.cue_id, text=orig_text))
            else:
                validated.append(out)

        return validated

    def _build_inputs(self, cues: list[SubtitleCue]) -> list[CueInput]:
        return [
            CueInput(
                cue_id=cue.index,
                start_time=_srt_ts(cue.start),
                end_time=_srt_ts(cue.end),
                duration_secs=round(cue.duration, 3),
                cps=round(cue.cps, 1),
                original_text="\n".join(line for line in cue.lines if line.strip()),
            )
            for cue in cues
        ]

    def _apply_edits(
        self,
        original_cues: list[SubtitleCue],
        outputs: list[CueOutput],
    ) -> list[SubtitleCue]:
        """Apply validated outputs to a fresh copy of the original cues."""
        output_map = {out.cue_id: out for out in outputs}
        result: list[SubtitleCue] = []

        for cue in original_cues:
            out = output_map.get(cue.index)
            if out is None:
                result.append(cue)
                continue

            new_lines = [ln for ln in out.text.split("\n") if ln.strip()]
            if not new_lines:
                result.append(cue)
            else:
                result.append(
                    SubtitleCue(
                        index=cue.index,
                        start=cue.start,
                        end=cue.end,
                        lines=new_lines,
                    )
                )

        return result

    def _write_debug(
        self,
        scene_id: str,
        project_id: str,
        original_cues: list[SubtitleCue],
        edited_cues: list[SubtitleCue],
    ) -> None:
        from ytfactory.subtitles.writer import SRTWriter

        debug_dir = (
            Path("workspace") / "jobs" / project_id / "subtitle-debug" / "editor"
        )
        debug_dir.mkdir(parents=True, exist_ok=True)

        writer = SRTWriter()

        (debug_dir / f"{scene_id}-original.srt").write_text(
            writer.write(original_cues), encoding="utf-8"
        )
        (debug_dir / f"{scene_id}-edited.srt").write_text(
            writer.write(edited_cues), encoding="utf-8"
        )
        (debug_dir / f"{scene_id}-diff.md").write_text(
            self._build_diff_md(scene_id, original_cues, edited_cues),
            encoding="utf-8",
        )

    @staticmethod
    def _build_diff_md(
        scene_id: str,
        original_cues: list[SubtitleCue],
        edited_cues: list[SubtitleCue],
    ) -> str:
        lines = [
            f"# Subtitle Edit Diff — {scene_id}",
            "",
            f"Total cues: {len(original_cues)}",
        ]
        changed = 0

        for orig, edit in zip(original_cues, edited_cues):
            orig_text = "\n".join(orig.lines)
            edit_text = "\n".join(edit.lines)
            if orig_text == edit_text:
                continue
            changed += 1
            lines += [
                "",
                f"## Cue {orig.index}  [{_srt_ts(orig.start)} → {_srt_ts(orig.end)}]",
                "",
                f"**Before:** `{orig_text}`",
                f"**After:**  `{edit_text}`",
            ]
            if edit.cps > 20:
                lines.append(f"⚠ CPS: {edit.cps:.1f} (exceeds 20)")

        lines += ["", "---", f"Changed cues: {changed}/{len(original_cues)}"]
        return "\n".join(lines)
