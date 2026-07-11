"""
TTSDebugWriter — optional per-scene debug output for the TTS pipeline.

When TTS_DEBUG=true, writes a complete audit trail of every text
transformation for each scene to:

    workspace/jobs/<project>/tts-debug/scene-NNN/

Files written per scene:
  original.txt          — raw narration from scene-plan.json
  optimized.txt         — after SpeechOptimizer
  formatted.txt         — after SpeechFormatter (= payload sent to TTS)
  metadata.json         — voice, rate, pitch, style, language, timings
  provider_request.json — exact parameters sent to the TTS API
  provider_response.json — raw boundary events returned by the provider
  timing.json           — word-level boundaries (seconds)
  validation.json       — AudioValidator result

A TTS_DIAGNOSTICS.md summary is written to the tts-debug/ root at the
end of the run (call write_project_summary() after all scenes complete).

When TTS_DEBUG=false, all methods are no-ops — zero overhead.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ytfactory.shared.constants import WORKSPACE_DIR


class TTSDebugWriter:
    """
    Write TTS debug artefacts for one scene.

    Instantiate once per scene.  All write_* methods are no-ops when
    ``enabled=False``.
    """

    def __init__(self, project_id: str, scene_index: int, enabled: bool = True):
        self._enabled = enabled
        self._scene_index = scene_index
        self._project_id = project_id
        self._dir = (
            Path(WORKSPACE_DIR) / project_id / "tts-debug" / f"scene-{scene_index:03d}"
        )
        if enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    # ── Text stages ───────────────────────────────────────────────────────────

    def write_original(self, text: str) -> None:
        """Raw narration from scene-plan.json."""
        self._write_text("original.txt", text)

    def write_optimized(self, text: str) -> None:
        """After SpeechOptimizer — \\n\\n-separated spoken phrases."""
        self._write_text("optimized.txt", text)

    def write_formatted(self, text: str) -> None:
        """After SpeechFormatter — exactly what is sent to the TTS provider."""
        self._write_text("formatted.txt", text)

    # ── Provider round-trip ───────────────────────────────────────────────────

    def write_provider_request(self, params: dict) -> None:
        """Parameters sent to the TTS API (text, voice, rate, pitch, etc.)."""
        self._write_json("provider_request.json", params)

    def write_provider_response(self, boundaries: list[dict]) -> None:
        """Raw boundary events returned by the provider."""
        self._write_json("provider_response.json", boundaries)

    # ── Derived artefacts ─────────────────────────────────────────────────────

    def write_metadata(self, metadata: dict) -> None:
        """
        Synthesis session metadata.

        Recommended fields: voice, rate, pitch, style, language,
        scene_position, emotion, request_ms, response_ms, word_count.
        """
        self._write_json("metadata.json", metadata)

    def write_timing(self, boundaries: list[dict]) -> None:
        """Word-level timing boundaries in seconds."""
        self._write_json("timing.json", boundaries)

    def write_validation(self, result_dict: dict) -> None:
        """AudioValidator result dict (call result.to_dict())."""
        self._write_json("validation.json", result_dict)

    # ── Project-level summary ─────────────────────────────────────────────────

    @staticmethod
    def write_project_summary(
        project_id: str,
        scenes_metadata: list[dict],
        enabled: bool = True,
    ) -> None:
        """
        Write TTS_DIAGNOSTICS.md to the tts-debug/ root.

        Call once after all scenes have been processed.

        Args:
            project_id:      Project identifier.
            scenes_metadata: List of per-scene metadata dicts (from write_metadata).
            enabled:         No-op when False.
        """
        if not enabled:
            return

        debug_dir = Path(WORKSPACE_DIR) / project_id / "tts-debug"
        debug_dir.mkdir(parents=True, exist_ok=True)

        total = len(scenes_metadata)
        passed = sum(1 for m in scenes_metadata if m.get("validation_passed", True))
        total_duration = sum(m.get("duration_seconds", 0.0) for m in scenes_metadata)
        retries = sum(m.get("retry_count", 0) for m in scenes_metadata)
        provider = (
            scenes_metadata[0].get("provider", "unknown")
            if scenes_metadata
            else "unknown"
        )

        lines = [
            "# TTS Diagnostics Report",
            "",
            f"**Project:** `{project_id}`  ",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
            f"**Provider:** {provider}  ",
            f"**Total scenes:** {total}  ",
            f"**Validated:** {passed}/{total} passed  ",
            f"**Total duration:** {total_duration:.1f}s ({total_duration / 60:.1f} min)  ",
            f"**Total retries:** {retries}",
            "",
            "---",
            "",
            "## Per-Scene Summary",
            "",
            "| Scene | Voice | Style | Duration | Retry | Validated | Issues |",
            "|-------|-------|-------|----------|-------|-----------|--------|",
        ]

        for m in scenes_metadata:
            idx = m.get("scene_index", "?")
            voice = m.get("voice", "?")
            style = m.get("style", "?")
            dur = m.get("duration_seconds", 0.0)
            retry = m.get("retry_count", 0)
            ok = "✓" if m.get("validation_passed", True) else "✗"
            issues = "; ".join(m.get("validation_issues", [])) or "—"
            lines.append(
                f"| {idx:>3} | {voice} | {style or '—'} | {dur:.1f}s | {retry} | {ok} | {issues} |"
            )

        lines += [
            "",
            "---",
            "",
            "## Debug File Structure",
            "",
            "Each scene has its own subdirectory under `tts-debug/`:",
            "",
            "```",
            "tts-debug/",
            "├── TTS_DIAGNOSTICS.md       ← this file",
            "└── scene-NNN/",
            "    ├── original.txt         ← raw narration from scene-plan.json",
            "    ├── optimized.txt        ← after SpeechOptimizer",
            "    ├── formatted.txt        ← after SpeechFormatter (sent to TTS)",
            "    ├── provider_request.json",
            "    ├── provider_response.json",
            "    ├── metadata.json",
            "    ├── timing.json",
            "    └── validation.json",
            "```",
            "",
            "## Troubleshooting",
            "",
            "**First word clipped:** Compare `optimized.txt` and `formatted.txt`.",
            "Look for `..` (double period) in `formatted.txt` — this is the primary",
            "cause of first-word clipping at paragraph breaks.",
            "",
            "**Short duration / empty audio:** Check `validation.json` for issues.",
            "Check `provider_request.json` for the exact payload sent to TTS.",
            "",
            "**Wrong voice / prosody:** Check `metadata.json` for resolved voice,",
            "rate, and pitch. Verify `style` and `language` are as expected.",
        ]

        out = debug_dir / "TTS_DIAGNOSTICS.md"
        out.write_text("\n".join(lines), encoding="utf-8")

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _write_text(self, filename: str, content: str) -> None:
        if not self._enabled:
            return
        (self._dir / filename).write_text(content, encoding="utf-8")

    def _write_json(self, filename: str, data: object) -> None:
        if not self._enabled:
            return
        (self._dir / filename).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
