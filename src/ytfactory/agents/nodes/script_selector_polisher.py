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
from video_core.providers.llm.factory import get_llm_for_role

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
    """LLM provider pointed at ``script_polisher_model`` via the role-based
    factory — uses the "script" role as base, with an explicit override to the
    polisher model."""
    return get_llm_for_role(
        settings, "script", model_override=settings.script_polisher_model
    )


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


_EDITORIAL_FIX_SYSTEM_PROMPT = """\
You are a targeted script editor. You receive a finished documentary narration script
and a list of specific Editorial QA issues. Your ONLY job is to fix those exact issues
with the minimum change needed.

Rules (strictly enforced):
- Fix ONLY the issues listed. Leave everything else untouched.
- Do NOT restructure, reorder, or expand sections.
- Do NOT add new stories, metaphors, or ideas.
- Do NOT remove stories unless a duplicate-story issue explicitly names one to cut.
- Preserve the opening and closing lines unless they are the cited problem.
- Change less than 10% of the script. Stop if you need more — log it but keep what you have.
- Return the FULL corrected script, nothing else — no preamble, no JSON, no explanation."""

_EDITORIAL_CHECK_GUIDANCE: dict[str, str] = {
    "callback_to_opening": (
        "The ending does not call back to the opening image/hook. Add a brief echo of "
        "the opening in the final paragraph — a single line or image that mirrors the start. "
        "Do not add a new paragraph; weave it into the existing ending."
    ),
    "unnecessary_explanation": (
        "These sentences explain what the prior sentence already made the reader feel. "
        "Delete each one; the prior sentence does the work alone."
    ),
    "open_loop_payoff": (
        "A question or tension was planted early and never resolved. "
        "Add a short resolution in the final third of the script — one sentence is enough."
    ),
    "ending_vs_opening": (
        "The closing beat is weaker than the opening. Strengthen the final image or line "
        "so it lands with at least the same emotional weight as the opening."
    ),
    "sounds_translated": (
        "These sentences read as translated rather than originally written in English "
        "(literal phrasing, stiff constructions). Rewrite each one to sound natural — "
        "shorter words, looser sentence rhythm, idiomatic American English."
    ),
    "every_story_earns_place": (
        "These stories duplicate another story's narrative function. Cut or compress "
        "the weaker duplicate to a single sentence."
    ),
}


def _build_editorial_fix_prompt(script_text: str, flagged: list[tuple[str, dict]]) -> str:
    """Build the user prompt for a targeted Editorial QA fix pass."""
    issue_lines: list[str] = []
    for check_name, check in flagged:
        guidance = _EDITORIAL_CHECK_GUIDANCE.get(check_name, "Fix this issue.")
        note = check.get("note", "").strip()
        issue_lines.append(f"ISSUE — {check_name}")
        issue_lines.append(f"  What was flagged: {note or '(see evidence below)'}")
        issue_lines.append(f"  How to fix: {guidance}")

        # Per-check evidence to make the fix targetable
        if check_name == "callback_to_opening":
            opening = check.get("opening_image", "").strip()
            ending = check.get("ending_quote", "").strip()
            if opening:
                issue_lines.append(f"  Opening image/hook: \"{opening}\"")
            if ending:
                issue_lines.append(f"  Current ending beat: \"{ending}\"")
        elif check_name == "unnecessary_explanation":
            for v in (check.get("violations") or []):
                issue_lines.append(f"  Delete: \"{v}\"")
        elif check_name == "sounds_translated":
            for v in (check.get("flagged") or []):
                issue_lines.append(f"  Rewrite: \"{v}\"")
        elif check_name == "open_loop_payoff":
            q = check.get("question", "").strip()
            if q:
                issue_lines.append(f"  Unresolved question: \"{q}\"")
        elif check_name == "ending_vs_opening":
            opening = check.get("opening_beat", "").strip()
            closing = check.get("closing_beat", "").strip()
            if opening:
                issue_lines.append(f"  Opening beat: \"{opening}\"")
            if closing:
                issue_lines.append(f"  Closing beat (to strengthen): \"{closing}\"")
        elif check_name == "every_story_earns_place":
            for s in (check.get("stories") or []):
                if isinstance(s, dict) and s.get("duplicate_of"):
                    issue_lines.append(
                        f"  Story \"{s.get('name', '?')}\" duplicates \"{s['duplicate_of']}\""
                    )
        issue_lines.append("")

    issues_text = "\n".join(issue_lines).rstrip()
    return (
        f"Fix the following Editorial QA issues in the script below.\n\n"
        f"{issues_text}\n\n"
        f"=== SCRIPT ===\n{script_text}"
    )


def apply_editorial_fixes(
    script_text: str,
    flagged: list[tuple[str, dict]],
    settings: "Settings",
) -> str:
    """Targeted Editorial QA fix pass — fixes only flagged issues, one attempt.

    Returns the fixed script on success, or the original script if the LLM
    fails or returns suspiciously short content. Never raises.
    """
    if not flagged or not script_text.strip():
        return script_text

    try:
        llm = _get_polisher_llm(settings)
        user_prompt = _build_editorial_fix_prompt(script_text, flagged)
        response = llm.generate(
            user_prompt,
            system_prompt=_EDITORIAL_FIX_SYSTEM_PROMPT,
            temperature=0.3,
        )
        fixed = response.text.strip()
        if len(fixed) < len(script_text) * 0.7:
            logger.warning(
                "Editorial fix returned suspiciously short text ({} chars vs {} original) — keeping original",
                len(fixed), len(script_text),
            )
            return script_text
        return fixed
    except Exception as exc:  # noqa: BLE001
        logger.error("Editorial fix pass failed ({}); keeping original script", exc)
        return script_text


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
    # Guard: never overwrite script.md with empty content (e.g. when both
    # variants were empty because the composer was idempotency-skipped).
    if selected_script.strip():
        script_dir = Path(WORKSPACE_DIR) / project_id / "script"
        script_dir.mkdir(parents=True, exist_ok=True)
        (script_dir / "script.md").write_text(selected_script, encoding="utf-8")

    return {
        "selected_script": selected_script,
        "polisher_report": report,
        "script_md": selected_script if selected_script.strip() else state.get("script_md", ""),
    }
