# Image Prompt Generation & Escalation Spec (v3.0)

## 0. Purpose

Standardize how scene image prompts are built, scored, and escalated so that:

- Every prompt has an unambiguous, non-conflicting structure the model can follow.
- Vision QA gates on one canonical composite score, mapped to whatever `ImageReviewEngine` actually
  emits — not to an assumed metric set (see §6).
- Failed QA triggers a *targeted* rewrite of only the responsible prompt section, never a full rewrite.
- Cost is minimized by only escalating models when prompt refinement has been tried and failed.
- All thresholds/limits live in one config block (§4.0), not scattered as hardcoded numbers.
- There is a defined, non-blocking terminal state when even the premium model misses target.

This spec resolves duplication between the source strategy doc's Section 13 ("Adaptive Quality
Optimization") and Section 20 ("Self-Healing Image Pipeline"), plus the Model Registry doc's "Model
Selection Policy," into one canonical algorithm (§4). It also incorporates the eight Open
Implementation Decisions raised on this spec — each is addressed inline and cross-referenced below.

**Scope guard:** this pipeline generates **video scene images only**. It MUST NOT generate thumbnail
images, marketing assets, title cards, posters, or promotional artwork. `scene_importance` values in
this spec (hero, climax, opening_hook, closing_frame) refer to narratively significant *video* scenes —
not thumbnail generation, which is out of scope entirely and must be handled by a separate pipeline
(verification item — see §9.6).

---

## 1. Structured Prompt Schema

Prompts must be built and stored as **discrete, tagged sections**, not a flat string — required for §5
(targeted remediation) to work. Structure follows the recommended schema exactly (no extra sections
beyond it — `technical_quality` from the earlier draft has been folded into `style`, since a separate
section for it isn't in the agreed structure):

```json
{
  "scene_id": "scene_014",
  "sections": {
    "composition": "Landscape 16:9. Wide-angle 35mm lens. Over-the-shoulder view. Subject on right third. Foreground: incense smoke. Middle ground: subject. Background: temple courtyard, shallow depth of field.",
    "camera": "Eye-level, static tripod shot. No dutch angle.",
    "subject": "Elderly temple priest, saffron robes, hands folded at chest height.",
    "scene": "Dawn light through courtyard pillars, light fog.",
    "lighting": "Soft directional key light from left, warm 3200K, gentle rim light on subject's shoulder.",
    "color_palette": "Warm ochres and deep shadow browns, desaturated blues in background.",
    "style": "Photorealistic. Natural colors. Movie still. High dynamic range. Professional cinematography. 8k detail, sharp focus, natural skin texture, no plastic look.",
    "negative_constraints": "No text. No watermark. No logo. No illustration. No cartoon. No CGI. No duplicate subjects. No extra limbs. No cropped head."
  },
  "meta": {
    "scene_importance": "standard | hero | climax | opening_hook | closing_frame",
    "target_model": "flux-schnell | qwen-image | flux-dev"
  }
}
```

Rules:

- **Section order is fixed** and matches the priority order in §2 — composition first, negative
  constraints last, regardless of which model consumes it.
- The renderer concatenates sections in order when producing the final string prompt sent to the
  image model; the *structured* form is the source of truth and is what gets diffed/edited.
- Each section must stand alone with no cross-references to another section's wording (this is what
  makes single-section rewrites safe — see §5).
- **Implementation prerequisite (§9.2):** verify how `scene_planner.py` currently represents prompts.
  If they're flat strings today, migrate to this schema *before* wiring adaptive refinement — targeted
  remediation cannot work against an undifferentiated string.

---

## 2. Section Priority Order

1. Composition
2. Camera
3. Subject
4. Scene
5. Lighting
6. Color Palette
7. Style (includes technical/texture quality)
8. Negative Constraints

Composition + Camera together must occupy roughly the first 15–20% of the rendered prompt length.

**Conflict rule:** if two sections would contradict (e.g. Subject says "hands resting on knees" while
Negative Constraints says "no visible hands"), the section that most directly governs *framing*
wins — i.e. Composition/Camera > Negative Constraints > Subject. Prefer rephrasing the losing section
as a positive instruction rather than leaving a contradiction (e.g. Subject → "Hands remain outside
frame; upper-back composition").

---

## 3. Image Model Registry & Prompt Strategy

Qualitative columns below (Tier, Style, Speed priority) are retained for prompt-authoring guidance.
The **measured columns are placeholders** — populate with real production data before the adaptive
pipeline uses them for cost/escalation decisions (implementation prerequisite, §9.5). Do not let the
adaptive pipeline make cost trade-offs based on the qualitative "low cost / premium" labels once real
numbers exist — those labels are for humans reading this doc, not for the pipeline's logic.

| | FLUX.1-schnell | Qwen-Image | FLUX.1-dev |
|---|---|---|---|
| Model ID | `black-forest-labs/FLUX.1-schnell` | `Qwen/Qwen-Image` | `black-forest-labs/FLUX.1-dev` |
| Tier (qualitative) | Low cost | Medium cost | Premium |
| Role | Default / first-pass | Quality escalation | Final escalation, last resort |
| Prompt length | 250–350 words max | Higher complexity acceptable | Higher complexity acceptable |
| Prompt style | Short, explicit, minimal repetition | Rich environmental/lighting detail, cinematic storytelling | Maximum realism, maximum texture/lighting fidelity, richest environmental complexity |
| Speed priority | Fastest generation is a goal | Balanced | Ignore generation speed — optimize purely for quality |
| `cost_per_image` | **TBD — measure** | **TBD — measure** | **TBD — measure** |
| `average_latency` | **TBD — measure** | **TBD — measure** | **TBD — measure** |
| `success_rate` | **TBD — measure** | **TBD — measure** | **TBD — measure** |
| `average_vision_qa_score` | **TBD — measure** | **TBD — measure** | **TBD — measure** |
| `prompt_adherence_score` | **TBD — measure** | **TBD — measure** | **TBD — measure** |
| `failure_rate` | **TBD — measure** | **TBD — measure** | **TBD — measure** |

The renderer must apply model-specific formatting rules to the *same* structured sections (§1) rather
than maintaining three separate prompt copies — only rendering/verbosity differs per model, never
scene intent, camera angle, composition, subject identity, or emotional tone. Never reuse the exact
same rendered prompt string across two different models — always re-render from the structured
sections using that model's formatting rules in this table.

---

## 4. Canonical Generation & Escalation Algorithm

This replaces source-doc Sections 8–13, 17, and 20 (strategy doc) plus the "Model Selection Policy"
(Model Registry doc) with one three-tier algorithm.

### 4.0 — Configuration (implemented — no hardcoded thresholds in code)

**Status: implemented.** `EscalationConfig` (in `review_config.py`) loads these from real `.env` vars —
this is no longer a proposed shape, it's live:

```yaml
image_generation:            # implemented as EscalationConfig, loaded via IMAGE_ESCALATION_* env vars
  target_quality_score: 9.2      # single global acceptance threshold — applies to ALL tiers (§9.4)
  retry_threshold: 8.5           # below this, skip FLUX.1-schnell remediation and escalate directly
  premium_model_threshold: 8.5   # below this at Qwen-Image, still escalate to FLUX.1-dev (no cheaper option left)
  max_prompt_refinements: 1      # remediation retries — FLUX.1-schnell only (§5)
  max_model_escalations: 2       # FLUX.1-schnell → Qwen-Image → FLUX.1-dev
```

All threshold/limit references below use these names, not literal numbers — `_run_generation_strategy`
in `ImagePipeline` now reads them from `EscalationConfig` rather than hardcoding `9.2`/`8.5` inline.

### Step 0 — Scene classification
If `scene_importance` in {hero, climax} → skip directly to **Step 3**
(Qwen-Image), since remediation cost there is worth paying upfront for highest-visibility *video*
scenes. Standard/environmental/background scenes start at Step 1. Thumbnails never enter this
algorithm (§0 scope guard) — **confirmed implemented**: `_is_hero_scene` no longer checks for
`"THUMBNAIL"` (removed after an upstream grep confirmed no scene field ever set that value — it was
dead code, not live behavior).

**Note:** upstream scene metadata currently emits `narrative_role` values
(`STORY | ANALOGY | METAPHOR | EXPLANATION | ESTABLISHING | CTA`) and `importance` values observed
in production are limited to `standard | hero | climax`. The values `opening_hook` and `closing_frame`
appear only in this spec's schema example, never in live scene-plan data. If those narrative roles
are intended for future use, update `_is_hero_scene` and this step together; otherwise the spec
here matches the implementation.

### Step 1 — Candidate generation (FLUX.1-schnell)
- Generate **2 candidates**, different seeds, identical prompt (no intentional composition variance —
  only natural stochastic variation in clouds/foliage/micro-expression/shadow/texture).
- Run Vision QA (§6) on both. Keep the higher-scoring candidate. Discard the other.

### Step 2 — Threshold branch (FLUX.1-schnell) — **implemented**
- **`overall_status == PASS` and score ≥ `target_quality_score`** → Accept. Stop. (Per §6: a hard-
  constraint FAIL is never overridden by a high score — `_score_image` now returns
  `(score, overall_status, failure_reason)` and every branch checks both, not score alone.)
- **`retry_threshold` ≤ score < `target_quality_score`** (or `overall_status == FAIL`) → Targeted
  remediation (§5), up to `max_prompt_refinements` (currently 1):
  - `_refine_prompt_from_score` now takes the actual `failed_constraint` and maps it to a targeted
    addition (categories implemented: `anatomy`, `hand`, `composition`, `crop`, `framing`, `lighting`,
    `face`, `eye`, `text`, `watermark`, `realism`, `style` — broader than this spec's original §5
    table; §5 below has been expanded to match).
  - Regenerate **1** image.
  - Re-run Vision QA.
    - **PASS and ≥ `target_quality_score`** → Accept. Stop.
    - **Otherwise** → proceed to Step 3.
- **score < `retry_threshold`** → proceed to Step 3 directly (skip remediation — not cost-effective).

### Step 3 — First escalation (Qwen-Image)
- Carry forward the same structured sections (composition, framing, camera angle, subject identity,
  scene intent preserved verbatim per schema in §1). **Note:** this still assumes the §1 structured-
  prompt schema; prompts are still flat strings in production (`scene["visual_prompt"]`) — see §9 item
  2, which remains open.
- Apply Qwen-Image-specific rendering (§3) — enrich lighting/atmosphere language, do not change scene
  meaning.
- Generate **1 image. One try only — no remediation retry on this tier.** Run Vision QA.
  - **PASS and ≥ `target_quality_score`** → Accept. Stop.
  - **Otherwise** → proceed directly to Step 4. (`premium_model_threshold` doesn't gate whether to
    escalate — Qwen-Image is not the last tier, so any miss escalates; the config value exists for
    future tuning/telemetry, not as a bypass.)

### Step 4 — Final escalation (FLUX.1-dev) — **implemented (was previously unscored)**
- Carry forward the same structured sections again; scene intent/camera/composition/subject/tone
  unchanged.
- Apply FLUX.1-dev-specific rendering (§3) — maximum realism/texture/lighting fidelity, ignore
  generation speed.
- Generate **1 image. One try only — no remediation retry on this tier.** Run Vision QA — **tier-3
  output is now scored** (previously accepted unconditionally with no QA check at all).
  - **PASS and ≥ `target_quality_score`** → Accept. **(Single global threshold — no relaxed floor for
    the premium tier; see §9.4.)**
  - **Otherwise** → proceed to Step 5 (terminal fallback). No regeneration attempt here —
    accept-or-fallback only.

### Step 5 — Terminal fallback (flag / log / continue — non-blocking) — **implemented**
Matches the existing `IMG_007` / `IMG_008` project convention: flag, log, continue rendering. Never
block the render over one image.
- Accept the highest-scoring FLUX.1-dev candidate produced.
- **Implemented:** scene is recorded in `self._flagged_scenes` and written into `ImageArtifact` as
  `qa_status="flagged_below_target"`, `qa_score`, `qa_failure_reason` — this metadata now actually
  travels through the manifest, not just a documented intent.
- Human-review-queue surfacing (`human_review_scenes` node) — **not yet confirmed wired**; the
  manifest-level flagging is done, but whether it's additionally pushed into that queue is unconfirmed.
- Do **not** loop indefinitely and do **not** regenerate again — this is a hard stop. There is no
  fourth model and no second FLUX.1-dev attempt (`max_model_escalations: 2` is fully consumed).

---

## 5. Targeted Prompt Remediation Map

This remediation loop applies **only to FLUX.1-schnell (Step 2)**, bounded by `max_prompt_refinements`.
Qwen-Image and FLUX.1-dev each get exactly one generation attempt with no remediation retry (§4 Steps 3–4).

**Status: implemented** — `_refine_prompt_from_score` now accepts `failed_constraint` and maps
categories to targeted prompt additions. The implemented category list is broader than this spec's
original 6-field hard-constraint mapping, since it operates at a finer grain (e.g. splitting `anatomy`
into `hand`/`face`/`eye` sub-categories). Table below updated to match what's actually implemented:

| `failed_constraint` category | Prompt section(s) to update |
|---|---|
| `anatomy` | `subject` (general anatomy correction) |
| `hand` | `subject` **and** `composition` (hand-specific correction; often paired with framing fixes) |
| `face` | `subject` |
| `eye` | `subject` |
| `composition` | `composition` |
| `crop` | `composition` |
| `framing` | `composition` **and** `camera` |
| `lighting` | `lighting` |
| `text` | `negative_constraints` |
| `watermark` | `negative_constraints` |
| `realism` | `style` |
| `style` | `style` |

For `prompt_compliance`-type broad failures not covered by a specific category above, use the `reason`
string returned alongside the failure to identify the right section (e.g. a missing required object →
`scene`; wrong subject position → `composition`) — this constraint is broad by design, so remediation
must parse `reason`, not just the category name, in those cases.

Also retain, for numeric-score-only misses (hard constraints all passed, but `overall_score` still
under `target_quality_score`):

| Sub-quality issue | Prompt section(s) to update |
|---|---|
| Color balance / mood mismatch | `color_palette` |
| Object placement, non-hard-constraint | `scene` |

Never touch sections outside this map for a given failure; unrelated sections are preserved verbatim
to keep the scene consistent across regenerations. Each remediation pass must record:
`failed_constraint`, `reason` (verbatim from Vision QA), `sections_changed` — so repeated failures on
the same section across scenes can be audited later and fed back into prompt templates. **Note:** this
per-section targeting is still logically mapped onto a flat prompt string in production today (§9 item
2 — structured-prompt migration remains unimplemented), so "update this section" currently means
"append/adjust the corresponding phrase within the single prompt string," not a true isolated-section
rewrite yet.

**Important:** since a hard-constraint FAIL means `recommend_regeneration = true` regardless of any
score, and Step 2's remediation logic in §4 already treats any `overall_status == FAIL` as "below
target" — a hard-constraint failure on FLUX.1-schnell should always attempt the one allowed remediation
pass (targeting the section above) before escalating, same as a numeric miss. It does not need special-
case handling beyond picking the right section from this table.

---

## 6. Vision QA Scoring Model (confirmed — replaces earlier assumed composite)

§9.1 is now resolved: this is the real evaluation contract `ImageReviewEngine` uses, confirmed from
the actual review prompt/schema. It is **not** a weighted composite of independent sub-scores — it is
a **two-stage gate**:

### Stage A — Hard Constraints (binary, evaluated independently, never averaged)

| Constraint | What it checks |
|---|---|
| `prompt_compliance` | Every explicit prompt requirement — camera angle, composition, subject position, required/forbidden objects, framing, visibility requirements, foreground/background placement |
| `anatomy` | Hands, fingers, arms, legs, faces, eyes, body proportions — any severe defect fails |
| `required_visibility` | Explicit hidden/visible requirements from the prompt (e.g. "hands must remain outside the frame") checked exactly |
| `composition` | Camera angle, crop, foreground/middle/background, focal point — fails if materially different from spec |
| `required_objects` | Every required object present; an unexpected dominant object also fails this |
| `text` | Fails if text appears in the image when the prompt requested none |

**Rule:** if **any** hard constraint fails → `overall_status = FAIL`, `recommend_regeneration = true`,
immediately. Do not average a hard-constraint failure into a numeric score, and do not let strong
scores elsewhere compensate for it — this mirrors the anatomy-hard-floor idea from the earlier draft,
except it's now confirmed as the actual mechanism, applied to all six constraints, not just anatomy.

### Stage B — Numeric quality score (only computed if Stage A fully passes)

Only when every hard constraint passes does the engine compute a numeric `overall_score` and compare
it against `target_quality_score` (§4.0). `PASS` requires **both** all hard constraints passing *and*
`overall_score >= target_quality_score`.

### How this maps onto §4's algorithm

Every Vision QA check in Steps 2–5 must branch on `overall_status` first, not on a raw number:
- `overall_status == "FAIL"` → treat as below `target_quality_score` regardless of any numeric value
  (a hard-constraint failure with recommend_regeneration=true is not eligible for accept, no matter
  what `overall_score` says) — proceeds through the same escalation/remediation/fallback paths in §4.
- `overall_status == "PASS"` → accept, per the normal threshold logic already in §4.

### ⚠️ Two schema gaps to fix before this is wired in

1. **`text` is a defined hard constraint (rule 6) but is missing from the REQUIRED JSON output** — the
   schema only returns `prompt_compliance`, `required_visibility`, `composition`, `required_objects`,
   `anatomy`. Either add a `text` key to the JSON contract, or confirm text-detection is folded into
   one of the existing five keys (e.g. `prompt_compliance`) and document which.
2. **`overall_score` is referenced in the FINAL DECISION logic but absent from the REQUIRED JSON** —
   there is currently no field carrying the numeric quality score the spec's thresholds (§4.0
   `target_quality_score`, `retry_threshold`, `premium_model_threshold`) actually gate on. Add an
   `overall_score` (and ideally per-hard-constraint `reason` strings, which the schema already has, are
   good — keep those for §5's remediation root-cause logging).

Until both are fixed, `ImageReviewEngine`'s literal JSON output cannot drive §4's numeric thresholds —
only the binary FAIL path is currently well-defined.

---

## 7. Diversity Rule (candidate generation only)

When generating multiple candidates for the *same* prompt (Step 1), only these may vary naturally:
cloud formation, foliage, lighting rays, facial micro-expression, cloth folds, atmospheric particles,
texture, shadow placement. Camera angle, framing, subject, and scene meaning must not change between
candidates — that would defeat the purpose of "keep the higher-scoring one."

---

## 8. Cost Discipline

Priority order for improving a failing image, cheapest first:

1. Pick the better of 2 FLUX.1-schnell candidates (already free — no extra cost).
2. Targeted prompt remediation on FLUX.1-schnell (Step 2) — the only tier with a remediation retry,
   bounded by `max_prompt_refinements`.
3. Escalate to Qwen-Image (Step 3) — single attempt, no retry.
4. Escalate to FLUX.1-dev (Step 4) — single attempt, no retry, ignore generation speed here.
5. Terminal fallback, flag/log/continue (Step 5) — never a fourth model, never a second attempt on any
   premium tier, never a blocked render.

Never regenerate an already-accepted image. Hero/climax/opening_hook/closing_frame scenes bypass
Step 1 entirely and go straight to Qwen-Image (Step 0) since remediation cost there is worth paying
upfront for highest-visibility *video* scenes — this does not apply to thumbnails, which are out of
scope for this pipeline entirely (§0). Once §3's measured columns are populated, replace the
qualitative "cheapest first" ordering above with actual `cost_per_image` comparisons if real data
ever suggests a different ordering is more efficient.

---

## 9. Open Implementation Decisions

Status labels match the review: **Required** = implementation prerequisite, **Decision** = resolved
in this revision but flag if you disagree, **Recommended** = enhancement for later tuning.

1. **[Resolved]** Vision QA Score Mapping — confirmed. `ImageReviewEngine` uses a two-stage gate: six
   binary hard constraints (§6 Stage A) that fail the image outright regardless of any score, then a
   numeric `overall_score` (§6 Stage B) compared against `target_quality_score` — only if every hard
   constraint passed. §5's remediation table has been rewritten around these real field names.
2. **[Required — still open]** Structured Prompt Migration — confirmed still flat strings in
   production (`scene["visual_prompt"]`). §5's remediation targeting currently means "adjust the
   corresponding phrase within the flat prompt string," not a true isolated-section rewrite, until
   this migration happens.
3. **[Decision — resolved]** Vision QA Failure Policy — Step 5 now flags, logs (score + failure
   reason in metadata), and continues rendering, matching the `IMG_007`/`IMG_008` convention. Render
   is never blocked over a single image.
4. **[Decision — resolved]** Target Quality Threshold — unified to a single global
   `target_quality_score: 9.2` across all three tiers, including FLUX.1-dev (no relaxed 9.0 floor).
   Revisit only if operational data later shows a model-specific threshold improves throughput
   without materially reducing quality.
5. **[Required — still open]** Model Registry Calibration — populate §3's measured columns
   (`cost_per_image`, `average_latency`, `success_rate`, `average_vision_qa_score`,
   `prompt_adherence_score`, `failure_rate`) from real production data before the pipeline's cost
   logic relies on them.
6. **[Verification — resolved]** Thumbnail Pipeline Separation — confirmed via upstream grep: no
   production code ever set `importance`/`shot_type`/`scene_type` to `"THUMBNAIL"`. Dead code removed
   from `_is_hero_scene`; hero detection now uses only `("HERO", "CLIMAX")`.
7. **[Resolved]** Adaptive Threshold Calibration — implemented as `EscalationConfig`, loaded from real
   `IMAGE_ESCALATION_*` env vars (§4.0). No hardcoded `9.2`/`8.5` remain in `_run_generation_strategy`.
8. **[Resolved]** Prompt Refinement Mapping — implemented in `_refine_prompt_from_score`, which now
   takes `failed_constraint` and maps it to targeted additions. Implemented category set is broader
   than originally specified — §5 has been expanded to match (`hand`/`face`/`eye` split out from
   `anatomy`; `crop`/`framing` split out from `composition`; `watermark` added alongside `text`).
9. **[Likely resolved — needs final confirmation]** Vision QA JSON Schema Gap: `text` — `_score_image`
   now returns `failure_reason` and `_refine_prompt_from_score` handles a `text` category, which
   implies the underlying review schema was fixed to include it. **Not yet explicitly confirmed**:
   whether the actual `ImageReviewEngine`/review-prompt JSON output now has a real `text` key, or
   whether `_score_image` derives/parses this from elsewhere (e.g. a free-text `reason` field) without
   the upstream contract itself changing. Confirm which before treating this as fully closed.
10. **[Likely resolved — needs final confirmation]** Vision QA JSON Schema Gap: `overall_score` —
    `_score_image` returning a numeric `score` alongside `overall_status` implies this field now
    exists upstream, but this hasn't been explicitly confirmed the same way Gaps 1–7 were verified
    line-by-line. Confirm the real review-prompt JSON contract has been updated, not just that
    `pipeline.py` consumes a score value from wherever it currently comes from.
11. **[New — open]** Dual Remediation Systems — `_run_generation_strategy` (tier-escalation, now
    hard-constraint-aware per Gap 4) and `ImageRemediationOrchestrator` (human-scene-only, its own
    `max_attempts`/`auto_remediate` config) remain intentionally separate; docstrings now document
    why, but whether `ImageRemediationOrchestrator`'s human-scene remediation is now partially
    redundant with the more capable tier-escalation loop hasn't been evaluated. This affects total
    inference cost per video — worth a follow-up investigation, not a silent merge.
