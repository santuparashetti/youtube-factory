# Structural Retention Pass — Spec

## Why this pass exists

Four diagnostic runs proved the retention rules in `ATMA_THEORY_SCRIPT_WRITER.md`
cannot fire inside Pass 1. Pass 1 is, by its own hard constraints, a faithful
line-editor: an 80% coverage floor + a global "do not rearrange the order of
ideas" ban. Those constraints forbid the exact actions the retention rules
require — holding an open loop (move an answer to the end), breaking a parallel
example sequence (reorder/cut), adding a shadow beat (new connective material),
cutting a redundant story (drop coverage). Restructuring and faithful line-editing
are contradictory jobs; they cannot share one pass.

This pass does the structural work Pass 1 architecturally cannot. Pass 1 is left
exactly as-is.

## Where it runs

After the existing enhancer passes produce a clean, faithful, correctly-scoped
script (post Pass 1, and post Pass 2 if enabled). Input = the clean script.
Output = the same script, restructured for retention. Then → scene_planner as normal.

It is a distinct pass with its own prompt and its own permissions — NOT a mode of
Pass 1, NOT governed by Pass 1's coverage floor or no-reorder ban.

## The governing rule (Option 1)

HARD RULE: Reshape structure freely. Never change meaning.

The pass MAY:
- reorder ideas and stories
- cut a story or passage entirely if removing it strengthens the whole
- move where a question is answered (hold it open, pay it off late)
- add short connective/transitional lines and a shadow-beat line
- merge or split passages for momentum

The pass MUST NOT:
- invent philosophy or add a teaching not in the input
- change the meaning of any retained insight, story, or metaphor
- alter the mandated closing brand block (closing line / CTA / signature) —
  hard-preserved verbatim, same as elsewhere in the pipeline

Reordering and cutting are NOT meaning changes. They are the job.

## The five structural moves (the pass's checklist)

1. OPEN LOOP — Ensure one question is planted early and its answer deferred to
   near the end. If the input answers a compelling question immediately, move the
   answer so the question stays open across the body.
2. BREAK PARALLEL EXAMPLES — No more than two same-shape examples back to back.
   If the input runs three+ stories of identical structure (e.g. "told it was
   impossible → did it anyway"), either cut the weakest or separate them with a
   register shift (direct address / modern moment / stillness).
3. SHADOW BEAT — Insert one honest moment of weight before the climax, so the
   final rise has something to rise against.
4. DEPTH OVER COVERAGE — If two stories carry the same truth, keep the strongest
   and cut the other. Completeness is not the goal; impact is.
5. CLIMAX BREATH — One quiet line between the emotional peak and the brand
   sign-off. The peak is never stepped on by branding.

## Faithfulness — meaning-only, non-blocking flag (NOT auto-revert)

After restructuring, run a faithfulness check that compares MEANING, not structure:

- Extract the set of core insights/teachings/stories from the INPUT.
- Verify each retained item in the OUTPUT still carries the same philosophical
  meaning (not twisted, not fabricated, not contradicted).
- A story that was CUT is fine (that's move 4). A story REORDERED is fine
  (that's move 1/2). Only a story/insight whose MEANING changed, or a teaching
  that was INVENTED, is a violation.

On violation: FLAG it (write to a report artifact, surface in logs / review),
do NOT auto-revert. Rationale: an automatic revert cannot reliably distinguish
intended restructuring from meaning drift, and this pipeline has already been
burned twice by automatic guards (mode selection, coverage floor) silently
killing wanted edits. A visible flag lets a human judge; a silent revert would
sabotage the pass's purpose.

Report artifact fields (per run):
- moves_applied: which of the 5 moves fired, with a one-line note each
- stories_cut: list (title/gist) + one-line why
- stories_reordered: from→to position
- faithfulness_flags: [{item, input_meaning, output_meaning, severity}] — empty = clean
- structural_score (optional): coarse self-rating that the 5 moves landed

## What this pass does NOT do

- Does not target a word count (that's the enhancer's mode job — this runs after
  length is already right; if it cuts a redundant story, a downstream length note
  is fine but not this pass's concern).
- Does not re-polish wording (Pass 1 owns line-level).
- Does not touch the brand block.

## Config

- STRUCTURAL_PASS_ENABLED (bool, default true)
- STRUCTURAL_PASS_FAITHFULNESS_CHECK (bool, default true) — the meaning-only flag
- No coverage floor. No reorder ban. (That's the whole point.)

## Testing

- Unit: each of the 5 moves detectable on a crafted input that needs it.
- The eagle script (base_scripts/refined script files/word-for-those-who-say-cant-do-anything.md)
  is the canonical before/after fixture. Success criteria on eagle output:
  (a) the chick's "where is such strength in me?" is NOT answered immediately —
      held and paid off later;
  (b) the four same-shape parables (eagle/Bhagiratha/watchmaker/Vinoba) are
      reduced or separated — not four identical-shape stories in a row;
  (c) a shadow beat exists before the climax;
  (d) a breath line sits between the peak and "This is Atma Theory";
  (e) faithfulness check: no meaning-change flags (cuts/reorders are not flags).
- Faithfulness check unit tests: a meaning-preserving reorder → 0 flags;
  a fabricated teaching injected → 1 flag; a cut story → 0 flags.

## Token efficiency

- Single LLM call for the restructure; single call (or structured sub-call) for
  the faithfulness check. No iterative loop unless a move demonstrably failed.
- The pass prompt carries only the 5 moves + the hard rule + brand-block
  preservation — not the full ATMA_THEORY framework (that already ran in Pass 1).
  Keep the pass prompt lean; it inherits an already-shaped script.

## Break-in period (operational note, not code)

For the first few real scripts, human-review the restructured output before render
until the meaning-only check is trusted to hold. Not a permanent gate — a
confidence build. After that, the flag runs non-blocking and you glance only when
it fires.
