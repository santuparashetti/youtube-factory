# Task: Bring `src/ytfactory/images/pipeline.py` In Line With the Escalation Spec

## Context

`image-prompt-generation-spec-v1.md` defines the intended three-tier generation/escalation/QA
behavior. The model registry migration (`IMAGE_MODEL_TIER1/2/3_ID`+`_PROVIDER` in `.env`) is done, and
`IMAGE_REVIEW_ENABLED=true` is now live — so the gaps below are active in production, not dormant.
Fix `ImagePipeline` (`_run_generation_strategy`, `_is_hero_scene`, `_score_image`,
`_refine_prompt_from_score`, `_generate_two_candidates`) to close them. Do this as a series of small,
independently-testable changes — do not do one big rewrite.

---

## Gap 1 — Thresholds are hardcoded, not config-driven

**Current:** `9.2` and `8.5` are literals scattered through `_run_generation_strategy`.

**Fix:** Add a config object (Pydantic model or dataclass, matching whatever `Settings`/
`ImageReviewConfig` already uses) with:

```python
class EscalationConfig(BaseModel):
    target_quality_score: float = 9.2
    retry_threshold: float = 8.5
    premium_model_threshold: float = 8.5
    max_prompt_refinements: int = 1
    max_model_escalations: int = 2
```

Load from new `.env` vars (`IMAGE_ESCALATION_TARGET_QUALITY_SCORE`, `IMAGE_ESCALATION_RETRY_THRESHOLD`,
etc., with the defaults above so nothing breaks if unset). Replace every literal `9.2`/`8.5` in
`_run_generation_strategy` with reads from this config object. This alone makes future threshold
tuning a config change, not a code change.

---

## Gap 2 — Hero-scene escalation uses a lower bar (8.5) than standard scenes (9.2)

**Current:** In the hero-scene branch, tier 2 → tier 3 escalation triggers on `score < 8.5`. Standard
scenes require `9.2` on tier 1 before accepting.

**Fix:** Hero/climax scenes are supposed to get *more* quality assurance, not less. Change the hero-
scene branch to escalate to tier 3 when `score < target_quality_score` (i.e. the same `9.2`), using the
config value from Gap 1 — not a separate hardcoded `8.5`. If there's a real reason hero scenes should
tolerate a lower bar on tier 2 before paying for tier 3, that needs to be an explicit, named config
value (not a bare literal) with a comment explaining why — confirm which is actually intended before
picking.

---

## Gap 3 — Tier 3 (FLUX.1-dev) output is never Vision-QA'd

**Current:** Once escalation reaches tier 3 (in both the hero-scene branch and the standard-scene
Stage 3 branch), the code calls `self._provider.generate(tier3_request)` and returns immediately — no
score check.

**Fix:** After tier 3 generation, call `self._score_image(...)` same as the other tiers. Then:
- **`score >= target_quality_score`** → accept, return as normal.
- **`score < target_quality_score`** → this is the terminal-fallback case (spec §4 Step 5). Do not
  regenerate again — there's no tier 4. Instead:
  - Tag the scene/asset with `qa_status = "flagged_below_target"` plus the failing score and failure
    reason (see Gap 4 for where the reason comes from).
  - Write this into the manifest/scene metadata so it's visible downstream (check `ImageManifest` /
    `ImageArtifact` in `ytfactory.images.models` for the right field, or add one if none exists).
  - Do **not** block `video_renderer` or raise — this must stay flag-and-log-and-continue, matching
    the existing `IMG_007`/`IMG_008` convention project-wide. Confirm with whoever owns the
    `human_review_scenes` node whether flagged scenes should also be pushed into that queue.

---

## Gap 4 — Hard-constraint gate isn't wired into the tier-escalation decision loop

**Current:** `_score_image` / `_create_single_shot_reviewer` only pull `artifact.score` (a float) for
every tier-escalation decision. The hard-constraint gate (`overall_status`, per-constraint
`passed`/`reason`) is only read later, informationally, by the separate human-scene
`ImageRemediationOrchestrator` path — and that doesn't feed back into re-triggering tier escalation.

**Fix:** `_score_image` should return (or the caller should also fetch) `overall_status` alongside
`score`. Update every branch in `_run_generation_strategy` and `_generate_two_candidates` that
currently compares only `score` against a threshold to also check: if `overall_status == "FAIL"`,
treat the candidate as failing regardless of its numeric score (a hard-constraint failure must not be
masked by a high score elsewhere — this is the core rule from the spec's §6 Stage A). Concretely:

```python
def _score_image(self, scene, image_path, scoring_dir) -> tuple[float, str, str]:
    """Returns (score, overall_status, failure_reason)."""
    ...
    return artifact.score, artifact.overall_status, artifact.failure_reason  # adapt to real field names
```

Then every `if best_score >= 9.2` / `< 8.5` comparison becomes `if overall_status == "PASS" and
score >= target_quality_score`, etc. Note: per the spec, whoever owns the Vision QA prompt/schema
still needs to add a `text` key and an explicit `overall_score` field to the review JSON (documented
as open items in the spec) — this fix should be written to read the real field names once those are
confirmed, not to guess at them.

---

## Gap 5 — `_refine_prompt_from_score` is generic boilerplate, not targeted remediation

**Current:**

```python
def _refine_prompt_from_score(self, prompt: str, score: float) -> str:
    if score >= 9.0:
        return prompt
    adaptations = []
    if score < 8.5:
        adaptations.append("cinematic lighting, strong atmosphere")
    adaptations.append("photorealistic, high detail, correct anatomy, sharp focus")
    return f"{prompt}, {', '.join(adaptations)}"
```

This appends the same fixed phrases regardless of what actually failed.

**Fix (short-term, works on today's flat-string prompts):** Change the signature to take the failure
reason, not just the score:

```python
def _refine_prompt_from_score(self, prompt: str, score: float, failed_constraint: str, reason: str) -> str:
```

Map `failed_constraint` to the appropriate targeted addition (per the spec's §5 table — e.g.
`anatomy` → append anatomy-specific correction language; `composition` → append framing correction;
etc.) instead of one fixed suffix for every failure. This is a stopgap — the *real* fix is Gap 6.

**Fix (correct long-term fix — do this once §1's structured-prompt migration lands):** Once prompts
are structured sections (not flat strings), remediation should rewrite only the specific section
implicated by `failed_constraint`/`reason`, per the spec's §5 map, and leave every other section
untouched. Don't build the short-term fix in a way that blocks this — keep the failure-reason plumbing
(passing `failed_constraint`/`reason` through) the same either way, since that's the input the real
fix also needs.

---

## Gap 6 — `THUMBNAIL` still present in `_is_hero_scene`

**Current:**

```python
def _is_hero_scene(self, scene: dict) -> bool:
    importance = scene.get("importance", "").upper()
    shot_type = scene.get("shot_type", "").upper()
    scene_type = scene.get("scene_type", "").upper()
    return importance in ("HERO", "CLIMAX", "THUMBNAIL") or shot_type in ("HERO", "CLIMAX", "THUMBNAIL") or scene_type in ("THUMBNAIL",)
```

**Before fixing this, verify one thing first:** grep `scene-plan.json` generation (`scene_planner.py`)
for anywhere `"THUMBNAIL"` gets set as an `importance`/`shot_type`/`scene_type` value. If it's never
actually produced upstream, this is dead code and safe to delete outright. If it IS produced upstream
(meaning thumbnail scenes really do flow through this same image pipeline today), that's a real
conflict with the "video scene images only" scope guard — flag it back rather than silently deleting,
since removing it would change behavior for scenes currently in production use.

**Fix (assuming it's dead code):**

```python
def _is_hero_scene(self, scene: dict) -> bool:
    importance = scene.get("importance", "").upper()
    shot_type = scene.get("shot_type", "").upper()
    return importance in ("HERO", "CLIMAX") or shot_type in ("HERO", "CLIMAX")
```

---

## Gap 7 — Two overlapping remediation systems (tier-escalation vs. `ImageRemediationOrchestrator`)

**Do not silently merge these in this task.** This needs a design decision, not a quick fix:
- Document (in a code comment at the top of `ImagePipeline`, and in the spec) that there are
  currently two independent remediation mechanisms: (a) the tier-escalation loop in
  `_run_generation_strategy`, which runs for every scene and only sees `.score`; (b)
  `ImageRemediationOrchestrator`, which runs only for scenes with humans, after tier-escalation has
  already finished, and has its own `max_attempts`/`auto_remediate` config.
- Once Gap 4 is done (tier-escalation loop can see `overall_status`), evaluate whether
  `ImageRemediationOrchestrator`'s human-scene remediation is now partially redundant, or whether it's
  doing something genuinely different (e.g. deeper anatomy-specific passes) that should stay separate.
  Flag the finding rather than deciding unilaterally — this affects total inference cost per video.

---

## Suggested implementation order

1. Gap 1 (config plumbing) — foundational, everything else references these values.
2. Gap 6 (THUMBNAIL) — investigate first (grep upstream), fix or flag based on what's found.
3. Gap 2 (hero-scene threshold) — small, one-line-equivalent change once Gap 1 lands.
4. Gap 4 (hard-constraint gate in decision loop) — needed before Gap 3 and Gap 5 can be done correctly.
5. Gap 3 (tier-3 QA + terminal fallback) — depends on Gap 4's `_score_image` signature change.
6. Gap 5 (targeted remediation) — short-term fix now; long-term fix depends on the separate
   structured-prompt-schema migration (§1/§9.2 of the spec, not yet started).
7. Gap 7 (dual remediation systems) — investigate and report back; do not merge without a decision.

## Acceptance criteria

- [ ] No literal `9.2`/`8.5` remain in `_run_generation_strategy` — all read from `EscalationConfig`.
- [ ] Hero-scene tier2→tier3 escalation uses the same `target_quality_score` as standard scenes (or an
      explicitly-named, justified separate config value — not a bare literal).
- [ ] Tier 3 output is scored; scenes below target get `qa_status = "flagged_below_target"` + reason
      recorded in the manifest, without blocking the render.
- [ ] Every tier-escalation accept/reject decision checks `overall_status` in addition to `score`.
- [ ] `_refine_prompt_from_score` (or its replacement) receives and uses the actual failure
      reason/constraint, not just the numeric score.
- [ ] `THUMBNAIL` references in `_is_hero_scene` are either removed (if dead code, confirmed via grep)
      or flagged back with findings (if not dead code).
- [ ] A short doc comment or note explains the relationship between the two remediation systems; no
      silent merge happened without a reported decision.
- [ ] Existing tests still pass; new tests cover each gap fix above independently.
