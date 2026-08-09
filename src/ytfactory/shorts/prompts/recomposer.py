"""LLM prompt for the Shorts targeted recomposer (S2b recomposition phase)."""

from __future__ import annotations

from ytfactory.shorts.models import ShortsScript, ShortsScriptQAReport


RECOMPOSER_SYSTEM_PROMPT = """\
You are an editorial recomposer, not a fresh script generator.

Your job is surgical: preserve everything that works and rewrite only what is broken.

RULES — you must follow all of these:
1. Preserve every section marked as "preserve" exactly as it appears. Do not paraphrase, \
condense, or improve preserved sections. Return them verbatim.
2. Rewrite only the sections marked as "rewrite". Rewrite them to fix the diagnosed problem.
3. Do not rewrite a strong hook unless QA identified a hook problem.
4. Do not remove genuine standalone value.
5. Do not introduce generic motivational language ("unlock your potential", "transform your life").
6. Do not introduce promotional CTA language ("watch the full video", "subscribe").
7. Do not reveal the complete parent-video answer in the rewritten content.
8. If cross-Short similarity is the problem, change the evidence, narrative mechanism, or \
example — do not merely rephrase the same story in different words.
9. The recomposed Short must remain within the word-count constraints (90–120 words total).
10. The final open_loop must end with a genuine curiosity gap — an unresolved question.
11. Write like a thoughtful human speaking naturally, not like an AI content generator.

WHAT YOU MUST RETURN:
Return a JSON object with exactly the five section keys.
For sections marked "preserve": return the original text verbatim.
For sections marked "rewrite": return the improved version.

Return strict JSON only. No markdown. No preamble. No commentary.
"""


def build_recompose_prompt(
    script: ShortsScript,
    qa_report: ShortsScriptQAReport,
    sibling_scripts: list[ShortsScript],
    parent_script_md: str,
) -> str:
    preserve = qa_report.preserve_sections
    rewrite = qa_report.rewrite_sections
    instruction = qa_report.specific_instruction

    preserve_block = ", ".join(preserve) if preserve else "none"
    rewrite_block = ", ".join(rewrite) if rewrite else "none"

    siblings_block = ""
    for sibling in sibling_scripts:
        siblings_block += f"""
--- Sibling Short ({sibling.short_id}) ---
{sibling.full_script}
"""

    cross_note = ""
    if qa_report.cross_short:
        cross_note = f"""
CROSS-SHORT SIMILARITY PROBLEM:
{qa_report.cross_short.overlap_reason}

The rewritten sections must NOT share the same evidence, characters, setting, or \
narrative sequence as the sibling Short(s) above.
"""

    return f"""\
You are recomposing a YouTube Shorts script that failed quality review.

ORIGINAL SCRIPT (short_id: {script.short_id}):

HOOK:
{script.hook}

SETUP:
{script.setup}

STORY:
{script.story}

REVELATION:
{script.revelation}

OPEN_LOOP:
{script.open_loop}

---
QA FAILURE DIAGNOSIS:
Failed dimensions: {", ".join(qa_report.failed_dimensions) if qa_report.failed_dimensions else "none"}
Specific instruction: {instruction if instruction else "Fix the diagnosed failures."}

SECTIONS TO PRESERVE (return verbatim): {preserve_block}
SECTIONS TO REWRITE: {rewrite_block}
{cross_note}
SIBLING SHORTS (do not duplicate their content):
{siblings_block if siblings_block else "(none)"}

PARENT VIDEO SCRIPT (context only — do not repeat its complete answer):
{parent_script_md[:2000]}{"..." if len(parent_script_md) > 2000 else ""}

---

Return JSON with exactly these five keys:
{{
  "hook": "...",
  "setup": "...",
  "story": "...",
  "revelation": "...",
  "open_loop": "..."
}}
"""
