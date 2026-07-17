# ADR-0010 Addendum: Implementation Notes & Open Follow-ups

**Status:** Tracking
**Relates to:** ADR-0010 (Light Normalization Stage)
**Owner:** YouTube Factory

---

# Purpose

ADR-0010 has been implemented. This addendum records where the implementation deviated from or extended the original spec, and tracks a small number of open items that should be resolved — ideally before ADR-0011's implementation leans further on them, since ADR-0011's Input Contract assumes fully-normalized, correctly-flagged input from this stage.

---

# What Shipped (Summary)

- `LightNormalizationPipeline` — LLM call at temperature=0, preserve-first prompt.
- Scripture protection implemented via **pre-extraction**, not just instruction: Devanagari/Kannada/Tamil/etc. Unicode-range spans and `<scripture>...</scripture>` markers are replaced with `{{SCRIPTURE_N}}` placeholders before the LLM sees the text, and restored byte-for-byte afterward.
- `NormalizationValidator` — four automated checks: change-ratio bound, scripture placeholder match, paragraph-order invariant, no-new-content (Jaccard token overlap).
- Fallback-to-original on validation failure.
- Rename to `DocumentaryScriptEnhancerPipeline` with backward-compat alias; all 2201 existing tests pass unchanged.
- Pipeline wiring in both `run()` and `run_incremental()`.
- CLI: `ytfactory normalize <id>` and `--script` import on create.
- 24 new tests.

---

# Deviations Worth Recording

## 1. Scripture protection is stronger than specified

ADR-0010 asked for scripture spans to be passed through "byte-for-byte unchanged." The implementation goes further — spans are **extracted before the LLM call and replaced with placeholders**, so the model never sees the actual scripture text at all, rather than seeing it and being instructed not to alter it.

This is a strict improvement: it removes the risk class entirely (an in-context instruction being followed) rather than mitigating it. No action needed — recording this so the design intent is understood by whoever reads the code later.

## 2. Fallback behavior is more conservative than specified

ADR-0010 said a failed validation check should "block promotion of that stage's output to the next stage." The implementation instead **falls back to the original (unnormalized) transcript** and continues the pipeline, rather than halting it.

This is arguably the better behavior — the pipeline stays live and downstream stages get an unnormalized-but-intact input instead of nothing — but it's a deviation from what the ADR literally specified, so noting it here rather than leaving it implicit.

---

# Open Follow-ups

## 1. Change-ratio threshold: 15% vs. ADR's "low single-digit" example

The ADR's example for the change-ratio bound was "a low single-digit percentage change." The shipped threshold is 15% — a meaningfully wider allowance. On a stage that's supposed to be conservative, this leaves room for genuine rewriting to pass validation undetected.

**Action:** Confirm whether 15% was chosen after measuring real transcripts (i.e., legitimate light-normalization edits actually land in that range), or whether it's a placeholder. If the latter, tighten it once there's a representative sample of real output to calibrate against.

## 2. Span-level ambiguity flagging: status unconfirmed

ADR-0010's Ambiguity Handling section specified two distinct behaviors:
- **Document-level fallback** for validation failures — this shipped.
- **Span-level flagging** for individual ambiguous repetitions the normalizer isn't confident about (flag, don't silently decide) — status not confirmed from the implementation summary.

**Action:** Confirm whether span-level flagging was implemented. If not, this is a real gap, not a nice-to-have — it was the direct fix for the "clearly not intentional" ambiguity problem the ADR called out, and ADR-0011's Pass 1 fidelity work will have less signal to work with without it.

## 3. Scripture detection coverage for untagged, non-Devanagari text

Detection covers Unicode-range scripts and explicit `<scripture>` tags. Given this is Kannada-language spiritual content, romanized/transliterated Sanskrit **without diacritics and without explicit tags** — plausible in raw ASR output — would not be caught by either mechanism.

**Action:** Test against a real transcript containing untagged romanized verses to confirm this gap is or isn't a practical problem. This was the residual risk ADR-0010 flagged and the reason it recommended source-side marking as a fast follow.

## 4. Option 2 (STT) input path — confirmed deferral, not a gap

`ytfactory create --audio discourse.mp3` was correctly deferred since the STT pipeline doesn't exist yet. No action needed now; flagging here only so it stays visible as a tracked item for when the STT stage is built, at which point the CLI hook into Light Normalization should be straightforward given the stage already treats "receive a transcript" as its only contract.

---

# Recommendation

Items 1 and 2 are worth resolving before ADR-0011 goes much further, since ADR-0011's Fabrication Guardrail and Pass 1 fidelity gate are designed assuming a fully-normalized, correctly-flagged input. Item 3 can be validated in parallel. Item 4 has no near-term action.
