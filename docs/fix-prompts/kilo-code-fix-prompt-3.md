# Fix prompt for Kilo Code — documentary script enhancer duration correction failure

Paste everything below as one message, in the same session/repo.

---

## Rules — same as before

1. **Fix ONLY the item below. Nothing else.** Do not touch scene planner, motion, VOICE_ENABLED, or brand-card logic from previous sessions.
2. **Diagnose before you fix.** Do not guess at a fix and apply it. Add logging/prints first, run it, show me the actual evidence, THEN fix based on what the evidence shows.
3. **Minimum diff.** Smallest change that fixes it.
4. **Limit your output.** No full file dumps — show only file paths, exact changed lines, and the log/evidence output.
5. **No claiming "fixed" without proof.** Verification numbers required, not a description of what should happen.

---

## Item — duration correction (Pass 3) has no effect, pipeline aborts

**Symptom from the log:** Documentary Script Enhancer pipeline, `test-grass-that-refused-to-die`:
- Pass 2 (Viewer Retention Optimization) finishes at iteration 1 with Narrative Score 9.4/10, and the script measures **5.8 min** (target 8 min ±1, so 2.2 min under tolerance).
- Pass 3 (Duration correction — expanding) runs an LLM call (~9.6 sec).
- After Pass 3, duration is measured again: **still exactly 5.8 min.**
- Pipeline aborts: `Duration correction failed: 5.8 min is 2.2 min under target after Pass 3`.

The fact that duration is IDENTICAL before and after an expansion pass (not just still-short, but bit-for-bit the same number) is the key clue — investigate this specific fact first.

### Step 1 — diagnose why Pass 3's output isn't changing the measured duration

Find the Pass 3 implementation (`ytfactory.script_enhancer.pipeline`, function around line 786-871 based on the log — likely named something like `_correct_duration` or similar; grep for "Duration correction" and "Pass 3" in that file).

Add temporary logging immediately before and after Pass 3 to capture:
- Word count of the script going INTO Pass 3.
- Word count of the script coming OUT of the Pass 3 LLM call (raw response, before any parsing/validation).
- Word count of whatever script object is actually used for the duration measurement that triggers the abort.

Run it once and show me these three numbers. This will tell us which of these is happening:
(a) The LLM's response genuinely wasn't longer (unlikely given 9.6 sec is normal for a real generation, but check).
(b) The LLM's response WAS longer, but got discarded/not merged back into the script object used downstream (most likely, given the log).
(c) The correction succeeded and updated the script, but the duration-measurement function was called on the wrong variable (a leftover reference to the pre-Pass-3 script).

### Step 2 — fix based on what Step 1 shows

- If (b) or (c): fix the specific line where the Pass 3 output should replace the working script variable, or where the duration function reads from the wrong variable. Do not touch the LLM prompt/call itself.
- If (a): the LLM call itself isn't expanding enough. In that case, check the Pass 3 prompt template — does it tell the model the exact word-count gap to fill (e.g. "add ~450 words")? If it only says something vague like "expand this script," make the prompt specify the exact current word count, the exact target word count, and the exact gap, so the model has a concrete number instead of a vague instruction.

### Step 3 — fix the earlier contributing issue: Pass 2 exits without checking duration

In Pass 2's iteration loop (Viewer Retention Optimization, max 2 iterations), the exit condition currently appears to only check Narrative Score (it stopped at iteration 1 once score hit 9.4, even though duration was already 2.2 min short). Add duration-within-tolerance as part of the loop's exit condition — if duration is still out of tolerance, run a 2nd iteration (up to the existing max of 2) before falling through to Pass 3, rather than exiting early on narrative score alone.

## Verify

Report, with real numbers from an actual run:
1. Word count into Pass 3, word count out of Pass 3 (raw LLM response), word count of the script object used for the final duration check — all three, to prove the merge/measurement bug is fixed.
2. Final script duration after your fix, on the same source script. Must be within 6-8 min.
3. Confirm the pipeline no longer aborts at the `documentary_enhancer_duration` stage.
4. Confirm Pass 2 now considers duration in its exit condition (show the iteration count it actually ran).

| Check | Before | After |
|---|---|---|
| Word count in/out of Pass 3 | ? (add this) | ? |
| Duration after Pass 3 | 5.8 min (unchanged) | ? |
| Pipeline aborts? | yes | ? |
| Pass 2 iterations run | 1 (score-only exit) | ? |
