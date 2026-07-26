"""Parser for structured scene-retry LLM responses.

The scene planner's per-scene retry loop asks the LLM to return a single
JSON object (not the batch visual-prompt array format) describing the fix
for one flagged scene. This module is the ONLY parser for that response —
see docs/script/task-2.2-retry-engine-reliability.md Phase 4.
"""

from __future__ import annotations

import json
import re

from loguru import logger

RETRY_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "scene_id": {"type": "integer"},
        "visual_prompt": {"type": "string", "minLength": 50},
        "changes_made": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "violation_addressed": {"type": "string"},
    },
    "required": ["scene_id", "visual_prompt", "changes_made", "violation_addressed"],
    "additionalProperties": False,
}

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")
_REQUIRED_FIELDS = ("scene_id", "visual_prompt", "changes_made", "violation_addressed")


def parse_retry_response(raw: str, expected_scene_id: int) -> dict | None:
    """Parse an LLM retry response. Handles raw JSON, markdown-fenced JSON,
    leading/trailing whitespace, and JSON embedded in surrounding prose.

    Returns None on any parse or schema failure, with detailed logging —
    never returns a partially-valid result.
    """
    if not raw or not raw.strip():
        logger.error("Scene {} | retry response is empty", expected_scene_id)
        return None

    text = raw.strip()

    fence_match = _FENCE_RE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()
        logger.debug("Scene {} | stripped markdown fence from response", expected_scene_id)

    if not text.startswith("{"):
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start != -1 and json_end > json_start:
            text = text[json_start:json_end]
            logger.debug("Scene {} | extracted JSON object from response", expected_scene_id)
        else:
            logger.error(
                "Scene {} | retry response contains no JSON object\n"
                "Raw response (first 500 chars):\n{}",
                expected_scene_id,
                raw[:500],
            )
            return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(
            "Scene {} | JSONDecodeError: {} at line {}, column {} (char {})\n"
            "Problematic section:\n{}",
            expected_scene_id,
            exc.msg,
            exc.lineno,
            exc.colno,
            exc.pos,
            text[max(0, exc.pos - 50) : exc.pos + 50],
        )
        return None

    if not isinstance(data, dict):
        logger.error("Scene {} | retry response JSON is not an object: {!r}", expected_scene_id, data)
        return None

    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        logger.error(
            "Scene {} | schema missing fields: {}\nGot keys: {}",
            expected_scene_id,
            missing,
            list(data.keys()),
        )
        return None

    if data["scene_id"] != expected_scene_id:
        logger.error(
            "Scene {} | scene_id mismatch: expected {}, got {}",
            expected_scene_id,
            expected_scene_id,
            data["scene_id"],
        )
        return None

    visual_prompt = data["visual_prompt"]
    if not isinstance(visual_prompt, str) or len(visual_prompt.strip()) < 50:
        logger.error(
            "Scene {} | visual_prompt is empty or too short: {!r}",
            expected_scene_id,
            (visual_prompt or "")[:100],
        )
        return None

    if not isinstance(data["changes_made"], list) or len(data["changes_made"]) == 0:
        logger.error("Scene {} | changes_made is empty or not a list", expected_scene_id)
        return None

    return data
