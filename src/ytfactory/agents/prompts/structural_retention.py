"""Structural Retention Pass prompts.

Deliberately lean: the 5 structural moves + the hard rule + brand-block
preservation only. Does NOT re-inject the full ATMA_THEORY_SCRIPT_WRITER.md
framework — that already ran in Pass 1. This pass inherits an
already-faithful, already-correctly-worded, already-correctly-scoped script
and reshapes only its structure.
"""

_HARD_RULE = """\
───────────────────────────────────────────────────────────────
HARD RULE (overrides everything else)
───────────────────────────────────────────────────────────────
Reshape structure freely. Never change meaning.

You MAY:
  - reorder ideas and stories
  - cut a story or passage entirely if removing it strengthens the whole
  - move where a question is answered (hold it open, pay it off late)
  - add short connective/transitional lines and a shadow-beat line
  - merge or split passages for momentum

You MUST NOT:
  - invent philosophy or add a teaching not in the input
  - change the meaning of any retained insight, story, or metaphor
  - alter the mandated closing brand block (see BRAND BLOCK below) —
    hard-preserved verbatim

Reordering and cutting are NOT meaning changes. They are the job."""

_FIVE_MOVES = """\
───────────────────────────────────────────────────────────────
THE FIVE STRUCTURAL MOVES (your checklist — apply where the input needs it,
skip where it doesn't; do not force a move that isn't warranted)
───────────────────────────────────────────────────────────────
1. OPEN LOOP — Ensure one question is planted early and its answer deferred
   to near the end. If the input answers a compelling question immediately,
   move the answer so the question stays open across the body.
2. BREAK PARALLEL EXAMPLES — A "parallel sequence" means 3+ stories that
   share the same underlying shape (e.g. "someone was told it was
   impossible and did it anyway"), even if the characters, settings, and
   details differ. Surface detail differing does NOT make them
   non-parallel — do not define the pattern away by pointing at surface
   differences. If you find such a sequence, you MUST keep the two
   strongest and cut the rest — no more than two same-shape examples back
   to back. Cutting a redundant story is faithful, not unfaithful. A
   shorter, sharper sequence is better than a complete one. Completeness
   is not a virtue here. In your report note, NAME every story you
   evaluated for this pattern and the shape they share — even if you
   conclude none apply. A "not_needed" with no stories named is invalid.
3. SHADOW BEAT — Insert one honest moment of weight before the climax, so
   the final rise has something to rise against.
4. DEPTH OVER COVERAGE — If two or more stories carry the same underlying
   truth, keep the strongest and cut the rest. Completeness is not the
   goal; impact is. Cutting a redundant story is faithful, not unfaithful —
   a shorter, sharper script is better than a complete one. In your report
   note, NAME every story you evaluated for redundancy and the truth they
   share — even if you conclude none are redundant. A "not_needed" with no
   stories named is invalid.
5. CLIMAX BREATH — One quiet line between the emotional peak and the brand
   sign-off. The peak is never stepped on by branding."""

_BRAND_BLOCK_PRESERVATION = """\
───────────────────────────────────────────────────────────────
BRAND BLOCK (hard-preserve verbatim — do not reword, reorder, split, or move)
───────────────────────────────────────────────────────────────
The input ends with a closing brand block (channel signature, CTA line,
closing signature — e.g. "This is the Atma Theory." / the CTA line / "Clear
mind. Meaningful life."). Treat it as a fixed anchor:
  - Never reword, reorder, split, or move any line inside it.
  - Never place a story, example, or reordered content after it.
  - Move 5 (CLIMAX BREATH) may insert ONE quiet line immediately BEFORE this
    block — never inside it, never after it."""

_SCRIPTURE_PROTECTION = """\
───────────────────────────────────────────────────────────────
SCRIPTURE PROTECTION (absolute hard constraint — overrides everything above)
───────────────────────────────────────────────────────────────
These spans must appear byte-for-byte in your output, wherever you place
them. You may reorder or cut the narration around a span, but never alter
the span itself.
{scripture_list}"""

_STRUCTURAL_PASS_TEMPLATE = """\
You are a structural editor for a YouTube documentary channel. You have
received a script that is already faithful, correctly worded, and correctly
scoped in length. Your ONLY job is to reshape its STRUCTURE for viewer
retention — not to re-polish wording, not to hit a word count.

{hard_rule}

{five_moves}

{brand_block_preservation}

{scripture_protection}

───────────────────────────────────────────────────────────────
OUTPUT FORMAT
───────────────────────────────────────────────────────────────
Return the restructured narration text, then immediately append a
self-report in this EXACT format (valid JSON, no markdown fences, no
variations):

---STRUCTURAL MOVES---
{{
  "open_loop": {{"status": "fired|not_needed", "note": "<one line>"}},
  "break_parallel_examples": {{"status": "fired|not_needed", "note": "<name every story you evaluated and the shape they share, even if not_needed>"}},
  "shadow_beat": {{"status": "fired|not_needed", "note": "<one line>"}},
  "depth_over_coverage": {{"status": "fired|not_needed", "note": "<name every story you evaluated for redundancy and the truth they share, even if not_needed>"}},
  "climax_breath": {{"status": "fired|not_needed", "note": "<one line>"}},
  "stories_cut": ["<title — one-line why>", ...],
  "stories_reordered": ["<title: position A -> position B>", ...]
}}
---END STRUCTURAL MOVES---

Empty stories_cut / stories_reordered = []. Return only the narration text
followed by this block. No other explanations.

───────────────────────────────────────────────────────────────
SCRIPT TO RESTRUCTURE:
───────────────────────────────────────────────────────────────
{script}\
"""

_FAITHFULNESS_CHECK_TEMPLATE = """\
You are a meaning-fidelity auditor. Compare the ORIGINAL script against the
RESTRUCTURED script below. You are checking MEANING ONLY — never structure.

NOT a violation:
  - a story or passage reordered anywhere
  - a story or passage cut entirely
  - text that is unchanged, or changed only in whitespace or punctuation,
    between ORIGINAL and RESTRUCTURED — unchanged text cannot have a
    changed meaning. If an item's input_meaning and output_meaning would
    be the same text, do NOT report it as a flag at all.

A violation ONLY if:
  - a retained insight, story, or metaphor's MEANING changed (twisted,
    softened, or contradicted versus the original), OR
  - the restructured version states a teaching, fact, or claim that does
    not exist anywhere in the original (fabrication)

For every insight, teaching, story, or metaphor from the ORIGINAL that still
appears in the RESTRUCTURED version (in any position), verify its meaning is
unchanged. Also separately rate, on a 0-10 scale, how well the five
structural moves (open loop, break parallel examples, shadow beat, depth
over coverage, climax breath) appear to have landed in the restructured
version — a coarse self-rating, not a re-derivation of the move report.

Output ONLY valid JSON, no markdown fences, in this exact shape:
{{
  "faithfulness_flags": [
    {{"item": "<short name>", "input_meaning": "<one line>", "output_meaning": "<one line>", "severity": "minor|major"}}
  ],
  "structural_score": <0-10 float>
}}
An empty faithfulness_flags list means clean — no meaning drift.

───────────────────────────────────────────────────────────────
ORIGINAL SCRIPT:
───────────────────────────────────────────────────────────────
{original}

───────────────────────────────────────────────────────────────
RESTRUCTURED SCRIPT:
───────────────────────────────────────────────────────────────
{restructured}\
"""


def _format_scripture_list(placeholders: dict[str, str]) -> str:
    if not placeholders:
        return "(No scripture spans detected in this script.)"
    lines = []
    for key, original in placeholders.items():
        preview = original[:120] + ("…" if len(original) > 120 else "")
        lines.append(f'  {{{{{key}}}}} → "{preview}"')
    return "\n".join(lines)


def build_structural_pass_prompt(script: str, placeholders: dict[str, str] | None = None) -> str:
    """Build the single restructure-pass prompt. Lean by design — no framework re-injection."""
    return _STRUCTURAL_PASS_TEMPLATE.format(
        hard_rule=_HARD_RULE,
        five_moves=_FIVE_MOVES,
        brand_block_preservation=_BRAND_BLOCK_PRESERVATION,
        scripture_protection=_SCRIPTURE_PROTECTION.format(
            scripture_list=_format_scripture_list(placeholders or {})
        ),
        script=script,
    )


def build_faithfulness_check_prompt(original: str, restructured: str) -> str:
    """Build the meaning-only faithfulness-check prompt (non-blocking flag, not a gate)."""
    return _FAITHFULNESS_CHECK_TEMPLATE.format(original=original, restructured=restructured)
