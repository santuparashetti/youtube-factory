# Fix prompt for Kilo Code — follow-up (regression from previous fix)

Paste everything below as one message, in the same session/repo where the previous fixes were applied.

---

## Rules — same as before

1. **Fix ONLY the one item below. Nothing else.** Do not touch shot_type, motion, subtitles, or VOICE_ENABLED logic again unless this fix requires editing the exact same function — in which case change only the lines needed for this item.
2. **Minimum diff.** Smallest change that fixes it.
3. **Limit your output.** No full file dumps. Show only the file path, the exact changed lines, and the verification numbers.
4. **No claiming "fixed" without proof.** Run the verification and paste actual output.
5. **This is a regression introduced by the brand-card fix you just made** (making the brand-card scene always the final scene). It now breaks the render entirely — this is more urgent than before, since previously the pipeline at least produced a final video.

---

## Item — brand-card scene (scene 11) uses the wrong asset path, breaking the whole render

**Symptoms from latest run:**
- `Scene 11: video clip missing or too small (workspace/jobs/test-grass-that-refused-to-die/video/scene-011.mp4)`
- `final.mp4 is missing — concatenation did not complete`
- `Final brand card scene uses wrong asset path`

**Diagnosis to do first:**
- Find where the brand-card scene (scene 11, the appended/final one) gets its asset path assigned — this is the same code path touched in the previous brand-card fix (`_mark_asset_scenes()` in `src/ytfactory/agents/nodes/scene_planner.py`, or wherever the fallback-append logic lives).
- Print/log the asset path it's currently assigning, and compare it against where the actual brand-card asset file lives on disk. Confirm the mismatch — is it a wrong directory, wrong filename, a placeholder/template string that was never substituted, or a path relative to the wrong working directory?

**Fix:**
- Correct the path assignment so it points at the real, existing brand-card asset file.
- Do NOT change the "brand card must always be the final scene" behavior itself — that part is correct and should stay. Only fix the path it's using.
- If the brand-card asset simply doesn't exist yet at any expected location, say so explicitly instead of guessing a path — report which paths you checked and that none of them resolved.

**Verify (must report all of these with real numbers/output, not assumptions):**
1. `scene-011.mp4` exists and its file size is non-trivial (report actual size in bytes/KB, not just "exists").
2. `final.mp4` exists after a fresh full pipeline run.
3. Re-confirm the earlier fixes weren't broken by this change: `shot_type` coverage still 100%, no 3+ consecutive identical motion types, no audio files generated with `VOICE_ENABLED=false`.
4. Report the new overall QA score and scene pass count (was 10/11 — should now be 11/11).

Report a before/after table:

| Check | Before this fix | After this fix |
|---|---|---|
| scene-011.mp4 exists/size | missing | ? |
| final.mp4 exists | missing | ? |
| Scenes passed | 10/11 | ? |
| shot_type coverage (regression check) | 100% | ? |
| Overall QA score | ? | ? |
