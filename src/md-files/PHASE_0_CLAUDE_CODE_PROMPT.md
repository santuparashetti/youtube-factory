# Claude Code Prompt — Phase 0 Structural Extraction

Paste this into Claude Code, run from repo root (`/home/santosh/pvt-files/youtube-factory`).

---

You are executing Phase 0 of `PHASE_0_ARCHITECTURE_SPEC.md`. This is a
**structural-only** migration: no behavior, output, or CLI changes.

## Step 0 — Re-verify before touching anything

The spec's Module Bucket Audit (§5) was built from documentation, and
the documentation has known stale spots (see AS-004 in the audit — docs
said 8/11 validators, actual was 12). Before moving a single file:

1. Run `find src/ytfactory -maxdepth 2 -type d` and diff it against §5's
   bucket table. Flag any path in the table that doesn't exist, and any
   real directory not accounted for in the table.
2. Open `src/ytfactory/video/ffmpeg.py` and confirm whether
   `render_continuous()` is a thin subprocess wrapper (Bucket A) or
   embeds `MotionPlanner`/`TransitionPlanner`/`EffectsPlanner` calls
   (Bucket B, per AS-002 in the audit). Report which, do not move it
   either way without confirming with me first.
3. Check `src/ytfactory/benchmark/` (new since 07-10) — is it scoped
   generically (could benchmark any pipeline stage) or specifically to
   vision-review (per `test_benchmark_vision_review.py`)? Report which;
   don't move it either way without confirming.
4. Report back the diff before proceeding to Step 1. Stop and wait for
   my go-ahead.

## Step 1 — Baseline

```bash
uv run pytest tests/ 2>&1 | tail -5
```
Record the pass count. Expected **2159 passing, 0 failing** per the
2026-07-12 incremental audit — if it differs, something changed since
then; report the delta before proceeding. This is the regression
tripwire for every subsequent step.

## Step 2 — P1 items already resolved, one open item to note

MW-001 (CTA missing from agentic path), MW-002 (script refinement
missing from sequential path), BI-001 (`GeminiScenePlanner` hardcoded),
and BI-002 (LLM factory error message) were all resolved as of the
2026-07-12 audit — confirmed, no action needed.

**One new open item, non-blocking:** MW-005 — `run_incremental()` in
`build/pipeline.py` still skips `ScriptEnhancerPipeline` (MW-002 only
fixed the full `run()` path). This doesn't block Phase 0 —
`build/pipeline.py` isn't in the Bucket A move set — but don't touch it
in this session, and don't mistake it for something the extraction
caused.

Also note: `providers/tts/elevenlabs.py` is a dead stub (DC-002, still
open) sitting inside the `providers/tts/` directory you're about to
move in Step 4. Move it as-is along with the rest of the directory —
do not fix, implement, or delete it in this pass. That's a separate,
smaller cleanup.

## Step 3 — Create the skeleton

```bash
mkdir -p src/video_core/{providers,models,domain}
touch src/video_core/__init__.py
touch src/video_core/providers/__init__.py
touch src/video_core/models/__init__.py
touch src/video_core/domain/__init__.py
```
Run tests. Commit: `chore: create video_core package skeleton`.

## Step 4 — Move providers, one type per commit

For each of `llm`, `search`, `image`, `tts` (base + factory files only
— explicitly exclude `providers/tts/pacing/`), `vision` (now includes
`llama_cpp_provider.py`, added since the 07-10 audit — move it along
with the rest of `providers/vision/`):

1. `git mv src/ytfactory/providers/<type>/ src/video_core/providers/<type>/`
2. Update every import site repo-wide (`grep -rl "ytfactory.providers.<type>" src/ tests/`).
3. `uv run pytest tests/`
4. If pass count matches baseline exactly, commit:
   `refactor: move providers/<type> to video_core`
5. If it doesn't match, stop and report the diff — do not proceed to
   the next provider type.

## Step 5 — Move LAMM (`models/`)

Same pattern as Step 4: `git mv src/ytfactory/models/ src/video_core/models/`,
update imports repo-wide, run tests, commit only on exact baseline match.

## Step 6 — Move generic domain models

Move only `LLMResponse`, `SearchResult`, `ImageRequest` out of
`src/ytfactory/domain/` into `src/video_core/domain/`. Leave `Project`
in `src/ytfactory/domain/` untouched — it's YT-pipeline-specific
(stage-status dict). Update imports, run tests, commit.

## Step 7 — Import direction lint

Add a CI check (ruff rule, import-linter, or a small script in
`scripts/check_layering.py`) that fails if any file under
`src/video_core/` imports from `src/ytfactory/`. Run it once to confirm
it currently passes (zero violations). Commit.

## Step 8 — Update docs

Update `CLAUDE.md` and `MASTER_CONTEXT.md` provider-path
references to `video_core.providers.*` and `video_core.models`. Do not
change any other content in those docs in this same commit.

## Rules for the whole session

- One module move = one commit. Never batch two module moves into one commit.
- If any test count drift happens, stop immediately and report — do not
  attempt to "fix forward" by editing test files to match new behavior.
  A test count drift means something outside pure relocation changed.
- Do not touch anything in Bucket B or Bucket C from the spec.
- Do not create `factory_sdk` or any factory scaffold — out of scope for
  this session.
- Report progress after each numbered step, don't run ahead silently.
