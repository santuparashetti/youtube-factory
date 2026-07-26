# Fix prompt for Kilo Code

Paste everything below as one message. Works fine in a brand-new session — it's self-contained. The only requirement is that the same project/repo (with `.env`, `scene_plan.json`, and the source files referenced below) is open in that session, since Kilo needs to actually read and edit those files, not just the description.

---

## Rules — read before doing anything

1. **Fix ONLY the 5 items listed below. Nothing else.** Do not refactor, rename, reformat, "improve," or touch any file/function not explicitly named. If you notice an unrelated issue, list it at the end under "Noticed but not fixed" — do not fix it.
2. **One item at a time.** Do item 1 fully (fix + verify), report the result, then stop and wait for me to say "continue" before starting item 2. Do not batch multiple items into one pass.
3. **Minimum diff.** Change the smallest number of lines that fixes the item. No rewriting a whole function/file when a 1–3 line change does it.
4. **Limit your own output.** Do not paste full file contents back to me. For each item, show only: the file path, the exact lines changed (a short diff, not the whole function), and the verification numbers. If a file is long, do not re-print it — just confirm the change was saved.
5. **No claiming "fixed" without proof.** Every item has a verification step with exact numbers. Run it and paste the actual numbers. If you can't run the pipeline, say so explicitly instead of guessing the outcome.
6. **This has failed 3 times already** (two runs at 96.94/100, then a 3rd run with 10 scenes — same defects every time). Do not repeat whatever was tried before. Find the actual line, not a workaround around it.

---

## Item 1 (critical) — `shot_type` is empty on 100% of scenes

**Problem:** `shot_type` is null/empty on every scene in `scene_plan.json` (0/9, then 0/10 scenes across 3 runs). This starves Image Prompt Engine and Motion Engine of the data they need — it's the root cause of weak image prompts and repetitive motion (see item 2).

**Fix:**
- Grep `shot_type` across `src/` (start with `src/ytfactory/agents/nodes/scene_planner.py`) to find where it's supposed to be set.
- Make it a required field in the ScenePlanner output schema/validation.
- If the LLM omits it, hard-default to `"medium_shot"` in code, at the single point scenes are constructed — not duplicated in each downstream engine.

**Verify:** Re-run scene planning only (not full pipeline if possible) and report: `shot_type` coverage = X/9 or X/10. Must be 100%.

---

## Item 2 — same motion repeats 3+ consecutive scenes

**Problem:** Motion Engine logs show `push_in/in` repeating identically across scenes 6–8. This is downstream of Item 1 — do Item 1 first, then check if this persists.

**Fix (only if it still occurs after Item 1 is verified):**
- In `src/video_core/cinematic/motion.py`, `MotionPlanner.plan()`, add a constraint: same motion type cannot be chosen for a 3rd consecutive scene. If it would repeat, force a different motion from the allowed set.

**Verify:** Report the motion type assigned to every scene, in order. Confirm no motion type appears 3+ times in a row.

---

## Item 3 — final scene is not the brand card

**Problem:** `_mark_asset_scenes()` in `src/ytfactory/agents/nodes/scene_planner.py` should always make the brand-card asset the final scene. It isn't firing.

**Fix:**
- Confirm whether it appends a brand-card scene when no closing/CTA match is found.
- Fix so a brand-card scene is always the final scene — matched or appended as fallback — including when loading a cached scene plan.

**Verify:** Report `scene_plan.json`'s last scene's `scene_type`. Must be `brand_card`.

---

## Item 4 — `VOICE_ENABLED=false` in `.env` is ignored, audio still generates

**Problem:** `.env` has `VOICE_ENABLED=false`. Audio/TTS is generated anyway on every run.

**Fix:**
- Grep every read of `VOICE_ENABLED` (`os.getenv`, `os.environ`, or a settings/config class).
- Common bug to check first: `os.getenv("VOICE_ENABLED")` returns the *string* `"false"`, which is truthy in Python — if the code does `if voice_enabled:` without converting to bool, it will always be true. Check this specifically.
- Also check load order — is `.env` loaded before this value is read?
- Fix at the actual read/branch point. Do not add a second redundant check elsewhere.

**Verify:** Run with `VOICE_ENABLED=false` and report the number of audio files generated. Must be 0.

---

## Item 5 (low priority, do last) — subtitle lines exceed 42 characters

**Problem:** Scenes 3 and 5 have subtitle lines over 42 characters.

**Fix:** Add line-wrap logic in CaptionGenerator to break at 42 chars max. Apply the same limit in the ASS Subtitle Engine config.

**Verify:** Report max subtitle line length across all scenes. Must be ≤ 42.

---

## After all 5 items

Report a single before/after table:

| Item | Before | After |
|---|---|---|
| shot_type coverage | 0% | ? |
| Consecutive identical motion | yes (6–8) | ? |
| Final scene type | not brand_card | ? |
| Audio files with VOICE_ENABLED=false | >0 | ? |
| Max subtitle line length | >42 | ? |
| Overall QA score | 96.94 | ? |

If any row didn't change, say so plainly — do not round up to "fixed."
