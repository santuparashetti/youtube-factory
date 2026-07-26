# Fix prompt for Kilo Code

Paste everything below as one message.

---

I have a recurring, unfixed defect in this pipeline. A QA review confirms **two consecutive runs scored identically (96.94/100)** — meaning previous attempts did not actually fix the root cause, only adjusted things around it. Do not repeat that pattern. Fix the root cause below, then prove it with numbers, not a claim.

## Root cause (confirmed by review data, not a guess)

`shot_type` is empty/null on **0 of 9 scenes** in the generated `scene_plan.json`, in both runs. This one missing field is why three separate symptoms keep appearing:

1. Motion Engine has no `shot_type` to base camera movement on, so it falls back to one default movement repeatedly. Confirmed in logs: `push_in/in` repeats identically across 3 consecutive scenes (scenes 6–8) — this is the "same motion / not smooth" symptom.
2. Image Prompt Engine has no `shot_type` to build cinematography language from, producing generic/weak prompts on all 9 scenes.
3. (Separate, critical, don't conflate with the above) Final scene is NOT the brand-card asset scene. The closing/CTA text is supposed to render over a dedicated brand-card scene appended as the last scene — that append is not firing, so it overlays plain footage instead. This is the "scene missing its effect" symptom.

## What to do, in order

**Step 1 — find where `shot_type` is supposed to be set.**
Run `grep -rn "shot_type" src/` across the repo (including `src/ytfactory/agents/nodes/scene_planner.py`, the scene-planner LLM prompt/schema, and the Image Prompt Engine). Identify exactly why the field comes back empty for every scene: is it missing from the LLM output schema, missing from the parsing step, or present but never propagated into `scene_plan.json`?

**Step 2 — fix `shot_type` at the source, not with a patch downstream.**
- Make `shot_type` a required field in the ScenePlanner's output schema/validation (not optional).
- If the LLM omits it, apply a hard default of `"medium_shot"` in code — do not rely on prompting the LLM harder to remember it.
- Do this once, at the point scenes are constructed, so Image Prompt Engine and Motion Engine both receive a non-empty value automatically. Do not add separate default logic in each downstream engine — one fix, one place.

**Step 3 — fix repeated identical motion (the "same motion" complaint).**
In the Motion Engine (`src/video_core/cinematic/motion.py`, `MotionPlanner.plan()`), add a constraint: the same motion type must not be chosen for more than 2 consecutive scenes. If the selected motion for a scene equals the previous scene's motion and would make a 3rd repeat, force a different motion type from the allowed set. Now that `shot_type` is populated (Step 2), verify this actually produces motion variety instead of still defaulting.

**Step 4 — fix the missing brand-card scene.**
Find `_mark_asset_scenes()` in `src/ytfactory/agents/nodes/scene_planner.py`. Confirm whether it appends a brand-card scene as the final scene when no closing/CTA/signature text match is found. If it doesn't fire in this case, fix it so a brand-card scene is ALWAYS the final scene — either matched or appended as a fallback — including on cached/reloaded scene plans (don't let a stale cached plan skip this).

**Step 5 — (low priority, only after 1–4 are done) subtitle line length.**
In CaptionGenerator, wrap/break subtitle lines at 42 characters max. Scenes 3 and 5 currently exceed it. Apply the same limit in the ASS Subtitle Engine config so both stay consistent.

## Do NOT

- Do not rewrite ScenePlanner, MotionPlanner, or the rendering pipeline wholesale. These are targeted fixes to specific functions.
- Do not touch anything unrelated to shot_type, motion variety, brand-card append, or subtitle line length.
- Do not mark this "fixed" based on code review alone — prove it per the verification step below.

## Verification (required before you report back)

Re-run the project's QA/validation pipeline on a fresh render and report these exact numbers:

- `shot_type` coverage: must be 9/9 (100%), not 0/9.
- No 3 consecutive scenes with the same motion type.
- Final scene's `scene_type` must be `brand_card`.
- All subtitle lines ≤ 42 characters.
- Compare the new QA score/verdict to the previous run (96.94/100) and show the diff — if it hasn't moved, the fix didn't land and you need to keep debugging, not report success.

Report back with the actual before/after numbers for each item above.
