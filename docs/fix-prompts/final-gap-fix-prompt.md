# Task: Final Gap-Fix Pass — Close Remaining Items from the Spec-to-Code Audit

## Context

`image-prompt-generation-spec-v1.md` (v3.2) and the full spec-to-code audit identified 5 remaining
items beyond the 7 gaps already fixed. Two are straightforward bugs (13, 14). Three involve a design
choice (3, 12, 15) — for those, a recommended default is given below so this can be done in one pass,
but each is called out explicitly so it can be reverted if the recommendation is wrong. Do each item
as an independent, separately-testable change.

---

## Item 13 — Enforce `max_prompt_refinements` (straightforward fix)

**Current:** `EscalationConfig.max_prompt_refinements` is loaded but never read in
`_run_generation_strategy` — exactly one refinement pass is hardcoded regardless of config value.

**Fix:** Change the Stage 2a remediation block from a single hardcoded attempt to a loop bounded by
`self._escalation_config.max_prompt_refinements`:

```python
refinement_count = 0
current_score = best_score
current_prompt = request.prompt
while (
    refinement_count < self._escalation_config.max_prompt_refinements
    and current_score < self._escalation_config.target_quality_score
    and current_score >= self._escalation_config.retry_threshold
):
    current_prompt = self._refine_prompt_from_score(current_prompt, current_score, failed_constraint)
    # ...regenerate, re-score...
    refinement_count += 1
    if new_overall_status == "PASS" and new_score >= self._escalation_config.target_quality_score:
        return output_path
    current_score = new_score
```

Adapt to match the actual variable names/control flow already in `_run_generation_strategy` — this is
the shape, not a literal patch. Since the default is `1`, behavior is unchanged unless someone
configures a higher value, so this is safe to ship without behavior-change risk today.

**Test:** set `max_prompt_refinements=2` in a test config, verify two refinement attempts actually
happen (not one), and verify `max_prompt_refinements=1` still behaves exactly as it does now.

---

## Item 14 — Complete the remediation audit trail (straightforward fix)

**Current:** `SceneRemediationArtifact.attempt_history` records `status`, `score`, `prompt_length`,
`passed` — missing `failure_category` (i.e. `failed_constraint`), `confidence`, `root_cause`,
`sections_changed`.

**Fix:** Add these fields to whatever record/dataclass backs each `attempt_history` entry, and
populate them at the point where `_refine_prompt_from_score` is called (it already has
`failed_constraint` and the Vision QA `reason` — thread those through):

```python
attempt_history.append({
    "status": status,
    "score": score,
    "prompt_length": len(prompt),
    "passed": passed,
    "failure_category": failed_constraint,   # already available at this call site
    "confidence": confidence,                 # from the Vision QA response, if present; else None
    "root_cause": reason,                     # the verbatim reason string from Vision QA
    "sections_changed": sections_changed,     # from the §5 remediation map lookup
})
```

If `confidence` isn't actually present anywhere in the Vision QA response, record `None` rather than
inventing a value — don't fabricate a field that doesn't exist upstream.

**Test:** trigger a remediation pass in a test, assert all four new fields are present and non-empty
(except `confidence`, which may legitimately be `None`) in the resulting `attempt_history` entry.

---

## Item 12 — Hero-scene classification mismatch (investigate first, then apply default if clear)

**Recommended default: option (a) — narrow the spec, not the code.** Reasoning: `_is_hero_scene`
matching only `("HERO", "CLIMAX")` was already verified once (Gap 6) via upstream grep with no
evidence `opening_hook`/`closing_frame` are ever produced. Extending code to handle values that don't
exist yet is speculative; narrowing the spec's Step 0 wording to match reality is lower-risk.

**Before applying the default:** grep `scene_planner.py` and any other scene-metadata-setting code one
more time, specifically for `"opening_hook"` or `"closing_frame"` as values (not just as node/step
names in the LangGraph flow, which is a different thing). If they genuinely never occur:
- Update `image-prompt-generation-spec-v1.md` §4 Step 0 to read `{hero, climax}` instead of
  `{hero, climax, opening_hook, closing_frame}`.
- No code change needed — `_is_hero_scene` is already correct.

**If they DO occur** (report this back rather than deciding unilaterally): don't change anything yet —
this would mean real scenes are currently NOT getting the tier-1-skip treatment the spec originally
intended for them, which is a product question about whether that's actually desired, not just a doc
fix.

---

## Item 15 — Anatomy hard floor (apply as defense-in-depth, clearly reversible)

**Recommended default: reinstate a lightweight version.** Reasoning: Stage A's binary `anatomy`
constraint should catch severe defects already, so this is genuinely defense-in-depth, not a primary
safeguard — cheap to add, costly to skip if Stage A ever has a false negative on a borderline case.

**Fix:** In `_compute_quality_scores` (or wherever the 5 quality sub-scores get averaged into
`overall_score`), add a floor check specifically on the anatomy-related sub-score component:

```python
def _compute_quality_scores(self, sub_scores: dict) -> float:
    composite = sum(sub_scores.values()) / len(sub_scores)
    anatomy_component = sub_scores.get("anatomy")  # adapt key name to whatever the real sub-score dict uses
    if anatomy_component is not None and anatomy_component < ANATOMY_FLOOR_THRESHOLD:
        composite = min(composite, ANATOMY_QUALITY_CAP)
    return composite
```

Add `ANATOMY_FLOOR_THRESHOLD` and `ANATOMY_QUALITY_CAP` (e.g. `6.0`, matching the earlier draft's
proposed cap) as named constants — ideally also config-driven (`EscalationConfig` or
`ImageReviewConfig`, whichever owns quality-scoring config) rather than hardcoded, consistent with
Item 13's fix above.

**If `_compute_quality_scores` doesn't actually have per-sub-score visibility at the point this would
need to be added** (e.g. if it only receives a pre-averaged number), report that back instead of
forcing a workaround — this may need a small refactor to pass sub-scores through rather than just the
average, and that's worth flagging rather than hacking around.

**Test:** construct a case where 4/5 sub-scores are high and the anatomy sub-score is low; verify the
composite is capped, not averaged up past the cap.

---

## Item 3 — `human_review_scenes` routing (apply lightweight default, flag if deeper wiring needed)

**Recommended default: do NOT build full automatic routing into the interactive CLI node.** That
node's whole design is interactive/manual, and force-feeding it programmatic entries could conflict
with its existing UX. Instead:

**Fix (lightweight):** Ensure flagged scenes are collected into a clearly-named, easy-to-find output —
e.g. a `flagged_scenes.json` (or similar) written alongside the manifest in the same output directory,
listing every scene with `qa_status="flagged_below_target"` plus its score/reason. This makes flagged
scenes discoverable without needing to touch the CLI node's internals.

```python
if self._flagged_scenes:
    flagged_path = output_dir / "flagged_scenes.json"
    flagged_path.write_text(json.dumps(
        [asdict(s) if is_dataclass(s) else s for s in self._flagged_scenes],
        indent=2,
    ))
```

Update the spec's §4 Step 5 and §9 item 3 to describe this lightweight approach instead of claiming
`human_review_scenes` node integration, once implemented — this closes the doc/reality gap by
matching the doc to what's actually built, rather than building something more invasive than needed.

**If you find `human_review_scenes_node` already has a hook for injecting programmatic entries**
(e.g. it reads from a file or queue rather than being purely interactive), report that back — it may
be cheaper to wire into that directly instead of adding a separate `flagged_scenes.json`.

---

## Suggested order

1. Item 13 (config enforcement) — isolated, no dependencies.
2. Item 14 (audit trail fields) — isolated, no dependencies.
3. Item 12 (hero-scene grep + spec narrowing, or report-back) — quick investigation, likely just a
   doc change.
4. Item 15 (anatomy floor) — small, but touch `_compute_quality_scores` carefully; check test coverage
   there first.
5. Item 3 (flagged-scenes file) — depends on nothing above; can be done anytime.

## Acceptance criteria

- [ ] `max_prompt_refinements` actually bounds the remediation loop; tested with a non-default value.
- [ ] `attempt_history` entries include `failure_category`, `confidence` (or `None`), `root_cause`,
      `sections_changed`.
- [ ] `_is_hero_scene` and the spec's §4 Step 0 agree with each other (either both two-value or both
      four-value) — no remaining contradiction, resolved via grep evidence, not assumption.
- [ ] Anatomy sub-score has a floor/cap mechanism, configurable, with a test proving it prevents
      averaging-up.
- [ ] Flagged scenes are written to a discoverable output (`flagged_scenes.json` or equivalent) even
      though full `human_review_scenes` CLI integration was intentionally not built.
- [ ] Spec doc (`image-prompt-generation-spec-v1.md`) updated to match whatever was actually
      implemented for items 3, 12, 15 — mirroring the pattern from the prior 7-gap fix round.
- [ ] Existing 2606+ tests still pass; new tests added per item above.
