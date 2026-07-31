"""Script Selector + Polisher node.

Receives the two composer variants (script_a / script_b) from graph state,
picks the stronger one via a top model, makes only the minimum necessary
changes (≤10%), and writes the final polished script back into `script_md`
(the backward-compat key every downstream stage reads) plus `script.md` on
disk. Replaces `editorial_qa` as the graph quality gate before
`human_review_final_script`.

The model runs through the existing LLM provider infrastructure with a model
override (same pattern as scene_planner's `_get_cheap_llm`) — never a hardcoded
API call. On any LLM/JSON failure the node falls back to a length heuristic and
flags the report so the human reviewer sees the polisher did not run cleanly;
it never blocks the pipeline.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

from loguru import logger

from ytfactory.agents.state import VideoState
from ytfactory.config.settings import Settings
from ytfactory.shared.constants import WORKSPACE_DIR
from video_core.providers.llm.base import LLMProvider
from video_core.providers.llm.factory import get_llm_provider

# ── System prompt (used verbatim — do not improvise) ──────────────────────────
SYSTEM_PROMPT = """You are a final polish editor for Atma Theory, a philosophical YouTube channel. Your job is precise and constrained.

You will receive two script variants (A and B) written by the same composer for the same source material.

STEP 1 — CHOOSE:
Read both scripts fully. Choose the one that is stronger as a whole. Base your choice on:
- Which opening hook pulls harder
- Which ending lands with more quiet force
- Which one has fewer seams — reads as one continuous voice
- Which open loop closes more naturally

State your choice and give 2-3 sentences explaining why. No more.

STEP 2 — POLISH:
Take the chosen script. Make only changes that are clearly necessary:
- A sentence that does not land
- A transition that jars the flow
- A word that weakens the line it sits in
- A rhythm break that would hurt TTS narration

DO NOT:
- Rewrite for style
- Restructure or reorder
- Add new ideas or metaphors
- Remove stories or examples
- Change the opening or closing unless they are broken
- Touch anything you are unsure about

HARD LIMIT: Your changes must affect no more than 10% of the script. If you find yourself changing more, stop and revert. The composer's voice is the asset — preserve it.

STEP 3 — RETURN:
Return the following JSON (and nothing else outside the JSON):
{
  "chosen": "A" or "B",
  "selection_reason": "<2-3 sentences>",
  "changes_made": ["<specific change> — <reason>"],
  "change_percentage": <int>,
  "unchanged_note": "<one sentence confirming structure/voice preserved>",
  "final_script": "<the full polished script text>"
}"""

# ── Channel guidelines (compact reference; the system prompt is authoritative) ─
_CHANNEL_GUIDELINES = (
    "Atma Theory — calm, cinematic documentary storytelling. Religion-agnostic, "
    "modern, timeless. Never preach, never sound like a guru or an academic. "
    "Natural American English, simple words, varied sentence length. Trust the "
    "viewer; never explain an idea twice. Silence is part of the storytelling."
)

_COMPOSER_FRAMEWORK_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "script_enhancer"
    / "prompts"
    / "ATMA_THEORY_COMPOSER.md"
)

# Sections of the composer framework worth sending as trimmed reference.
_WANTED_SECTIONS = ("SHAPE", "VOICE", "OUTPUT")


@functools.lru_cache(maxsize=1)
def _load_composer_guidelines() -> str:
    """Return the VOICE / SHAPE / OUTPUT sections of ATMA_THEORY_COMPOSER.md.

    Falls back to the full file when those sections can't be isolated (per the
    task's token-efficiency note)."""
    try:
        text = _COMPOSER_FRAMEWORK_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""

    # The doc delimits sections with lines of '=' — split on them, then the
    # chunks alternate header / body after the intro chunk.
    parts = [p.strip() for p in re.split(r"(?m)^={5,}\s*$", text)]
    picked: list[str] = []
    for i in range(1, len(parts) - 1, 2):
        header, body = parts[i], parts[i + 1]
        if any(tag in header.upper() for tag in _WANTED_SECTIONS):
            picked.append(f"{header}\n{body}")

    if len(picked) < len(_WANTED_SECTIONS):
        return text  # couldn't isolate all wanted sections — send the whole file
    return "\n\n".join(picked)


def _get_polisher_llm(settings: Settings) -> LLMProvider:
    """LLM provider pointed at `script_polisher_model` via the model-override
    pattern (same provider/base_url/api_key, different model name)."""
    model = settings.script_polisher_model
    provider_type = settings.llm_provider.lower()
    field = {
        "anthropic": "anthropic_model",
        "gemini": "gemini_text_model",
        "groq": "groq_model",
        "ollama": "ollama_model",
        "deepinfra": "deepinfra_model",
    }.get(provider_type)

    if model and field:
        return get_llm_provider(settings.model_copy(update={field: model}))
    return get_llm_provider(settings)


def _build_user_prompt(script_a: str, script_b: str, composer_guidelines: str,
                       channel_guidelines: str) -> str:
    return (
        "COMPOSER GUIDELINES (reference — the source framework both variants "
        f"were written under):\n{composer_guidelines}\n\n"
        f"CHANNEL GUIDELINES (reference):\n{channel_guidelines}\n\n"
        "Now choose between the two variants below and return the JSON described "
        "in your instructions.\n\n"
        f"=== SCRIPT A ===\n{script_a}\n\n"
        f"=== SCRIPT B ===\n{script_b}"
    )


def _parse_polisher_json(text: str) -> dict | None:
    """Best-effort parse: raw JSON → fenced ```json → first {...} span."""
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _json_candidates(text: str):
    text = (text or "").strip()
    if not text:
        return
    yield text
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        yield fenced.group(1).strip()
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        yield brace.group(0)


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _fallback_report(script_a: str, script_b: str) -> tuple[str, dict]:
    """Polisher LLM failed — pick the longer variant, no changes, flag it."""
    chose_a = len(script_a) >= len(script_b)
    selected = script_a if chose_a else script_b
    report = {
        "chosen": "A" if chose_a else "B",
        "selection_reason": (
            "Polisher did not run cleanly — fell back to the longer variant as a "
            "safe heuristic. No polishing was applied."
        ),
        "changes_made": [],
        "change_percentage": 0,
        "unchanged_note": "Structure and voice untouched (no polish pass ran).",
        "fallback": True,
    }
    return selected, report


def script_selector_polisher_node(state: VideoState) -> dict:
    project_id = state["project_id"]
    script_a = state.get("script_a", "") or ""
    script_b = state.get("script_b", "") or ""
    settings = Settings()

    # ── Choose + polish ──────────────────────────────────────────────────────
    selected_script: str
    report: dict
    try:
        llm = _get_polisher_llm(settings)
        user_prompt = _build_user_prompt(
            script_a, script_b, _load_composer_guidelines(), _CHANNEL_GUIDELINES
        )
        response = llm.generate(
            user_prompt,
            system_prompt=SYSTEM_PROMPT,
            temperature=settings.script_polisher_temperature,
            json_mode=True,
        )
        logger.info(
            "Script polisher tokens — input={} output={} (model={})",
            response.prompt_tokens,
            response.completion_tokens,
            settings.script_polisher_model,
        )
        data = _parse_polisher_json(response.text)
        final_script = (data or {}).get("final_script", "")
        if not data or not isinstance(final_script, str) or not final_script.strip():
            raise ValueError("polisher returned malformed JSON or empty final_script")

        selected_script = final_script.strip()
        report = {
            "chosen": str(data.get("chosen", "")).strip() or "A",
            "selection_reason": str(data.get("selection_reason", "")).strip(),
            "changes_made": list(data.get("changes_made", []) or []),
            "change_percentage": _coerce_int(data.get("change_percentage"), 0),
            "unchanged_note": str(data.get("unchanged_note", "")).strip(),
        }
    except Exception as exc:  # noqa: BLE001 — never block the pipeline on the polisher
        logger.error("Script polisher failed ({}); using length-heuristic fallback", exc)
        selected_script, report = _fallback_report(script_a, script_b)

    # ── Shim: selected_script → script_md (+ disk) so downstream needs no change
    script_dir = Path(WORKSPACE_DIR) / project_id / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "script.md").write_text(selected_script, encoding="utf-8")

    return {
        "selected_script": selected_script,
        "polisher_report": report,
        "script_md": selected_script,
    }
