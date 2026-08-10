"""Beat verifier — observability pass after recomposition.

Checks that every extracted beat survived the full composition pipeline.
Non-blocking: logs warnings for missing beats, writes beat-verification.json,
never raises to the caller.
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from video_core.providers.llm.base import LLMProvider
from ytfactory.beats_extractor.pipeline import format_beats_list
from ytfactory.shared.constants import WORKSPACE_DIR

_SYSTEM_PROMPT = """\
You are a script quality checker.

Below is a list of required beats and a final script.
For each beat, determine if it is present in the script.

A beat is "present" if:
- The specific story moment occurs in the script, OR
- The philosophical teaching is clearly stated, OR
- The metaphor mapping (X = Y) is explicitly expressed

A beat is "missing" if it was dropped, merged beyond recognition,
or only vaguely implied.

Return ONLY a JSON object. No preamble, no markdown fences.

Format:
{
  "beats": [
    { "id": 1, "present": true, "note": "brief reason" },
    { "id": 2, "present": false, "note": "brief reason" }
  ],
  "all_present": true,
  "missing_count": 0
}"""


def verify_beats(
    script: str,
    beats: list[dict],
    provider: LLMProvider,
    project_id: str,
) -> dict:
    """Check that all beats are present in the final script.

    Logs results at INFO/WARNING level and writes beat-verification.json.
    Returns the verification result dict; never raises.
    """
    if not beats or not script.strip():
        logger.warning("BeatVerifier: skipped — no beats or empty script")
        return {"beats": [], "all_present": True, "missing_count": 0, "skipped": True}

    beats_list = format_beats_list(beats)
    user_content = f"Required beats:\n{beats_list}\n\nFinal script:\n{script}"

    result: dict = {}
    try:
        response = provider.generate(
            user_content,
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.1,
        )
        raw = response.text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()
        result = json.loads(raw)
    except Exception as exc:
        logger.warning("BeatVerifier: LLM call failed ({}) — skipping verification", exc)
        return {"beats": [], "all_present": True, "missing_count": 0, "error": str(exc)}

    beat_results = result.get("beats", [])
    missing_count = result.get("missing_count", 0)
    all_present = result.get("all_present", True)

    for b in beat_results:
        bid = b.get("id", "?")
        present = b.get("present", True)
        note = b.get("note", "")
        if present:
            logger.info("BeatVerifier: Beat [{}] present — {}", bid, note)
        else:
            beat_desc = next((x["beat"] for x in beats if x["id"] == bid), "")
            logger.warning("BEAT MISSING: [{}] {} — {}", bid, beat_desc, note)

    if all_present:
        logger.info("Beat verification passed: {}/{} beats confirmed", len(beat_results), len(beat_results))
    else:
        logger.warning(
            "Beat verification: {}/{} beats confirmed, {} missing",
            len(beat_results) - missing_count,
            len(beat_results),
            missing_count,
        )

    out_path = Path(WORKSPACE_DIR) / project_id / "beat-verification.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("BeatVerifier: result written to {}", out_path)

    return result
