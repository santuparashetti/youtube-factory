"""Editorial QA Stage prompts. See EDITORIAL_QA_STAGE_SPEC.md.

Layer 1 (reviewer) and Layer 3 (promotion proposal draft) are the only two
LLM calls in this stage — the ledger is pure code. Both prompts require
quoted/named evidence for every verdict, flagged or clean: a verdict with no
evidence is discarded as INVALID (mirrors the Structural Retention Pass's
naming-requirement fix for the same rationalization failure mode).
"""

_EDITORIAL_QA_TEMPLATE = """\
You are an exacting documentary script editor doing a final read-through.
You do NOT rewrite anything — you judge what is already on the page and cite
your evidence. A verdict with no quoted evidence is worthless and will be
discarded — always quote or name the exact sentence, story, or beat you are
judging, even when your verdict is clean or positive. Showing what you
evaluated is not optional just because you found nothing wrong.

Run these six checks against the script below.

1. ending_vs_opening
   Quote the OPENING image/beat. Quote the CLOSING image/beat.
   verdict: "stronger" | "equal" | "weaker" — is the closing emotionally
   stronger than the opening?

2. every_story_earns_place
   List EVERY story in the script by name. For each, state its unique
   narrative function in one line, and whether it duplicates another
   story's function (name that story, or null if it doesn't).

3. unnecessary_explanation
   Quote every sentence that explains what the prior sentence already made
   the reader feel or understand (a "less is more" violation).
   verdict: "clean" if none found, otherwise the count as a string, e.g. "2".

4. callback_to_opening
   Quote the opening image. Quote the final paragraph.
   verdict: "yes" | "no" | "partial" — does the ending call back to the
   opening image?

5. sounds_translated
   Quote every sentence that reads as translated rather than originally
   written in English (literal phrasing, residual scaffolding like "the
   question is," stiff constructions).
   verdict: "clean" if none found, otherwise the count as a string, e.g. "1".

6. open_loop_payoff
   Name/quote the question or tension planted early. Name/quote where (or
   whether) it resolves.
   verdict: "paid off" | "paid off early" | "never resolved".

Output ONLY valid JSON, no markdown fences, in this exact shape:
{{
  "checks": {{
    "ending_vs_opening": {{"verdict": "stronger|equal|weaker", "opening_beat": "<quote>", "closing_beat": "<quote>", "note": "<one line>"}},
    "every_story_earns_place": {{"verdict": "clean|N duplicates", "stories": [{{"name": "<name>", "function": "<one line>", "duplicate_of": null}}], "note": "<one line>"}},
    "unnecessary_explanation": {{"verdict": "clean|N", "violations": ["<quote>", ...], "note": "<one line>"}},
    "callback_to_opening": {{"verdict": "yes|no|partial", "opening_image": "<quote>", "ending_quote": "<quote>", "note": "<one line>"}},
    "sounds_translated": {{"verdict": "clean|N", "flagged": ["<quote>", ...], "note": "<one line>"}},
    "open_loop_payoff": {{"verdict": "paid off|paid off early|never resolved", "question": "<quote>", "resolution": "<quote>", "note": "<one line>"}}
  }}
}}

───────────────────────────────────────────────────────────────
SCRIPT:
───────────────────────────────────────────────────────────────
{script}\
"""

_PROMOTION_PROPOSAL_TEMPLATE = """\
You are proposing a small, concrete addition to a documentary
script-generation prompt, based on a recurring editorial weakness across
multiple scripts. You are NOT rewriting the framework — a human will place
your draft text; you only draft it.

CHECK: {check_name}
FLAGGED in {flag_count} of the last {total} evaluated scripts (flag rate {flag_rate:.0%}).

EXAMPLE EVIDENCE FROM RECENT FLAGGED SCRIPTS:
{evidence_examples}

Propose ONE short, focused addition (a sentence or short paragraph, in the
voice of an existing prompt rule) that would prevent this recurring
weakness in future scripts. Do not restate the whole framework.

Output ONLY valid JSON, no markdown fences:
{{
  "summary": "<one line: what is recurring, plainly stated>",
  "proposed_prompt_addition": "<the draft text to add>"
}}\
"""


def build_editorial_qa_prompt(script: str) -> str:
    """Build the single Layer 1 reviewer prompt."""
    return _EDITORIAL_QA_TEMPLATE.format(script=script)


def build_promotion_proposal_prompt(
    check_name: str,
    flag_count: int,
    total: int,
    flag_rate: float,
    evidence_examples: list[str],
) -> str:
    """Build the Layer 3 promotion-proposal draft prompt. Only called when a
    pattern actually triggers (>= N of last M) — never on every run."""
    examples_text = "\n".join(f"  - {ex}" for ex in evidence_examples) or "  (none captured)"
    return _PROMOTION_PROPOSAL_TEMPLATE.format(
        check_name=check_name,
        flag_count=flag_count,
        total=total,
        flag_rate=flag_rate,
        evidence_examples=examples_text,
    )
