# Editorial QA Stage — Spec

## Purpose

A lightweight editorial reviewer that runs AFTER script generation (post
Structural Retention Pass). It does NOT rewrite. It judges the finished script
like an editor, produces an evidence-bearing report, accumulates findings across
scripts, and — only when a weakness RECURS — proposes a generation-prompt change
for human approval.

Three layers:
  1. QA REVIEWER   — per script → structured report. Flags, never gates.
  2. QA LEDGER     — append every report; persistent, keyed by check.
  3. PATTERN PROMOTER — when a check fails in >=N of last M scripts, surface to
     the human as a proposed generation-prompt change. Human approves; never auto-applies.

## Non-negotiable design rules (learned the hard way in this pipeline)

- FLAG, NEVER GATE. QA never blocks, rejects, or reverts a script. It reports.
  (The mode selector and coverage floor taught us silent auto-gates destroy good work.)
- NEVER AUTO-REWRITE. QA evaluates; it does not touch the script text.
- EVERY CHECK CITES EVIDENCE. No bare yes/no. Each check must quote/name the exact
  sentence, story, or beat it judges. A verdict with no cited evidence is INVALID
  and treated as "not evaluated" (same lesson as the structural pass's naming
  requirement that killed the rationalization bug).
- ONE HUMAN GATE AT PROMOTION. The learning loop runs automatically up to the point
  where a finding would change the generation prompt. There it STOPS and asks a
  human. This is the only thing preventing silent channel-voice drift over time.
- NUMERIC SCORES ARE INFORMATION, NOT GATES. An editorial score may be recorded;
  it must never trigger auto-rejection.

## LAYER 1 — QA REVIEWER (per script)

Input: final script (post structural pass) + a pointer to the opening and closing
paragraphs. Output: structured JSON report. Single LLM call, temp low (~0.2 —
this is judgment, not creativity).

### Checks (each returns: verdict, cited_evidence, note)

1. ending_vs_opening
   - Name the OPENING image/beat (quote it). Name the CLOSING image/beat (quote it).
   - Verdict: is the closing emotionally stronger than the opening? (stronger / equal / weaker)
   - Flag if equal or weaker.

2. every_story_earns_place
   - LIST every story in the script (name each).
   - For each, state its unique narrative function in one line.
   - Flag any story whose function DUPLICATES another's.
   - (Independent cross-check on the structural pass's own cutting decision.)

3. unnecessary_explanation
   - Quote any sentence that explains what the PRIOR sentence already made the
     reader feel or understand (a LESS IS MORE violation).
   - Verdict: clean / N violations. Flag if >0, list them.

4. callback_to_opening
   - Quote the opening image. Quote the final paragraph.
   - Verdict: does the ending call back to the opening image? (yes / no / partial)
   - This is the "loop closes last" check. Flag = report only; do NOT auto-enforce
     unless the human has set callback-required as house style (config flag below).

5. sounds_translated
   - Quote every sentence that reads as translated rather than originally written
     in English (literal phrasing, residual scaffolding like "the question is,"
     stiff constructions).
   - Verdict: clean / N flagged. List each.

6. open_loop_payoff
   - Name the question/tension planted early (quote it). Name where/whether it
     resolves (quote it).
   - Verdict: paid off / paid off early / never resolved.
   - Flag if paid off early (in body, not near end) or never resolved.

### Report shape (per script)
{
  script_id, timestamp,
  checks: {
    ending_vs_opening: {verdict, opening_beat, closing_beat, note},
    every_story_earns_place: {verdict, stories: [{name, function, duplicate_of|null}], note},
    unnecessary_explanation: {verdict, violations: [quoted sentences], note},
    callback_to_opening: {verdict, opening_image, ending_quote, note},
    sounds_translated: {verdict, flagged: [quoted sentences], note},
    open_loop_payoff: {verdict, question, resolution, note}
  },
  editorial_score: float,   # information only, never a gate
  invalid_checks: [names]   # any check that returned a verdict with no evidence
}

## LAYER 2 — QA LEDGER (across scripts)

- Append each per-script report to a persistent store (e.g. a JSONL file or table
  keyed by script_id, plus a per-check rollup).
- Cheap, append-only. No interpretation here — just accumulation.
- Rollup view per check: last M scripts, pass/flag per script, running flag-rate.
- This is the ONLY component that persists across runs. Keep it dead simple so it
  can't rot.

## LAYER 3 — PATTERN PROMOTER (periodic, human-gated)

- Trigger: after each QA run, evaluate the ledger rollup.
- Rule: if a check has FLAGGED in >= N of the last M scripts (defaults N=4, M=5 —
  configurable), it is a RECURRING weakness, not a one-off quirk.
- A single or occasional flag NEVER promotes. Only a pattern does. (This is the
  guard against overfitting one script's fix onto every future script.)
- On a recurring weakness, the promoter GENERATES A PROPOSAL:
    "Check X has flagged in 4 of the last 5 scripts. Example evidence: [...].
     Proposed generation-prompt addition: [draft text].
     Approve / edit / dismiss?"
- The proposal is surfaced to the HUMAN. Nothing is applied automatically.
- On approval: the human (or a coding agent they direct) adds the text to the
  generation framework / structural pass prompt. The promoter does NOT edit prompts itself.
- On dismiss: record the dismissal so the same pattern doesn't re-nag every run
  (cooldown: don't re-propose the same check for K runs unless the flag-rate rises).

## Config
- EDITORIAL_QA_ENABLED (default true)
- QA_PROMOTE_N / QA_PROMOTE_M (default 4 / 5)
- QA_PROMOTE_COOLDOWN_RUNS (default 5)
- QA_CALLBACK_REQUIRED (default false) — if true, callback_to_opening flag is
  treated as a house-style requirement; if false, it's report-only.
- QA never has a "reject" or "block" config. By design.

## Testing
- Per-check unit tests on crafted scripts: each check fires correctly on a script
  that needs it, stays clean on one that doesn't, and returns INVALID when the
  model gives a verdict with no cited evidence.
- Ledger: append + rollup correctness; flag-rate math.
- Promoter: does NOT propose on a single flag; DOES propose at N-of-M; respects
  cooldown after dismiss; never mutates a prompt file itself.
- Eagle script (post structural pass) as a live fixture end-to-end.

## Token efficiency
- One LLM call for the reviewer. Ledger + promoter are deterministic code (no LLM)
  except the proposal-draft text, which is one small call ONLY when a pattern
  actually triggers — not every run.

## WHO FIXES A FLAGGED SCRIPT

The QA stage reports; it does not fix. For a single script's flags, the fixer is
the HUMAN, at the review checkpoint (human_review_script), not an automated agent.

Flow for a flagged script:
  QA report → surfaced at the review pause, alongside the script →
  human edits script.md (or chooses regenerate) →
  QA RE-RUNS on the edit (per the review checkpoint's hash-guard) →
  continue when satisfied.

Why no auto-fixer (for now):
  An agent that rewrites flagged text is a rewrite loop. It can "fix" a flagged
  sentence in a way that breaks something QA did not flag (e.g. repairing a
  translated-sounding line while collapsing the open loop). Silent fix-one/
  break-another is the exact failure mode this pipeline is built to avoid. The
  QA stage's value is being a trustworthy report a human acts on — wiring an
  auto-fixer to it destroys that.

When a narrow auto-fixer MAY be added later (evidence-gated):
  Only after the ledger holds enough history (~15-20 scripts) to show which flag
  types are BOTH frequent AND mechanically safe to fix without judgment.
  - Safe candidate: residual scaffolding-phrase removal (deterministic).
  - NOT safe: ending_vs_opening, open_loop_payoff, every_story_earns_place —
    these require editorial judgment and stay human.
  A future fixer, if built, is narrow (one or two proven-safe flag types only),
  runs BEFORE the human review (so the human still sees and approves the result),
  and never touches judgment-heavy flags. Do NOT build this until the ledger
  justifies it; building it now is guessing which flags are safe.

## PHASE 2 (FUTURE) — SCOPED AUTO-FIXER

NOT part of the initial build. Documented here so the QA stage is built with the
right hooks, but implemented only AFTER the ledger holds real history (~15-20
scripts) showing which flag types are safe to automate. Build the QA stage +
ledger + promoter + human-fix FIRST; add this after.

The naive version (an agent that rewrites flagged text freely) is unsafe — it can
break something QA did not flag. This design earns automation by removing that
freedom:

1. SCOPED EDITS, NOT REWRITES.
   The fixer may only touch the EXACT spans QA cited (QA already quotes its
   evidence). It receives "rewrite THIS quoted sentence so it does not sound
   translated" — one span, in place — never "improve the script." It is never
   handed the surrounding text, so it physically cannot alter an unflagged beat
   (e.g. the open loop three paragraphs away). Scope is the safety.

2. FIX → RE-QA → DIFF-CHECK, AUTOMATICALLY.
   After each scoped fix, QA re-runs on the whole script.
   - Fix cleared its own flag AND introduced no new flags → accept.
   - Fix cleared its flag BUT a new flag appeared → AUTO-REVERT that fix and
     escalate to the human. The fixer cannot break something silently because
     QA gates its own output. Fix-one/break-another becomes detectable and
     caught, not invisible.

3. TIER-GATED ELIGIBILITY.
   Only local, mechanical, QA-verifiable flag types are auto-fix eligible.
   - Eligible (start here, conservative): sounds_translated, residual scaffolding.
   - NEVER eligible (judgment, ripples): ending_vs_opening, open_loop_payoff,
     every_story_earns_place, callback_to_opening. These always route to the human.
   Start the eligible list with scaffolding ONLY. Add a flag type to the eligible
   list only after it has flag-and-fixed cleanly by hand ~a dozen times in the
   ledger. Never auto-enable a flag type on a guess.

4. RUNS BEFORE HUMAN REVIEW, NOT INSTEAD OF IT.
   The fixer cleans the mechanical flags so the human review checkpoint focuses on
   judgment calls. The human still sees the result (including what was auto-fixed
   and any auto-reverts). It sharpens where human attention lands; it does not
   remove the human.

Config (Phase 2): QA_AUTOFIX_ENABLED (default false until ledger justifies),
QA_AUTOFIX_ELIGIBLE_FLAGS (default: scaffolding only).

Build note for Phase 1: expose QA's cited-evidence spans in the report in a form
a future fixer can target (per-flag quoted text + location), and keep QA callable
as a standalone re-check on a single script. That's all Phase 1 needs to do to
leave the door open — do not build the fixer itself yet.

## What this stage explicitly does NOT do
- Does not rewrite or touch the script.
- Does not gate, block, reject, or revert.
- Does not auto-edit any prompt or framework file.
- Does not promote a finding from a single script.
