# Claude Code Prompt — Phase 1 Step 2: Execute Settings Split

Paste into Claude Code, run from repo root. Executes the approved
proposal in `PHASE_1_SETTINGS_SPLIT_PROPOSAL.md`. Baseline: 2161
passing, 0 failing.

---

## Step 0 — Test-patch audit (gate — do not skip)

```bash
grep -rn "patch.*ytfactory\.config\.settings\.Settings\|patch.*Settings\b" tests/
```

For every hit, check whether the mock/patch is ever passed into a
`video_core/providers/*` constructor. If yes, note it — it will need
`patch("video_core.config.shared_settings.SharedSettings")` instead,
or an updated import target, after Step 3. Build the list now, fix
after the split (Step 5), not before — fixing them before the class
exists would just churn twice.

Report the list before proceeding to Step 1.

## Step 1 — Create `SharedSettings`

Create `src/video_core/config/shared_settings.py` with the exact 27
fields and defaults from the proposal's Step 3 code block. Copy it
verbatim — the proposal already has correct types/defaults sourced
from the live file.

```bash
mkdir -p src/video_core/config
touch src/video_core/config/__init__.py
```

Run tests (should be unaffected — nothing imports this yet). Commit:
`refactor: add video_core.config.SharedSettings (Phase 1 step 1/4)`

## Step 2 — Make `Settings` inherit from `SharedSettings`

In `src/ytfactory/config/settings.py`:
1. Add `from video_core.config.shared_settings import SharedSettings`
2. Change `class Settings(BaseSettings):` → `class Settings(SharedSettings):`
3. Delete the 27 now-inherited field declarations from `Settings` (they're
   declared once in `SharedSettings`, don't duplicate)
4. Leave the 3 dead fields (`kokoro_language`, `whisperx_model`,
   `request_timeout`) in place for now — separate cleanup, not this pass
5. Leave the 5 "lean Factory" ambiguous fields in `Settings` — add a
   one-line comment on each noting they were reviewed and intentionally
   kept factory-side (so a future reader doesn't re-litigate this)

Run tests. Every `ytfactory/` call site should be unaffected — if
anything fails here, it's almost certainly a field that got deleted
from `Settings` but wasn't actually one of the 27 (double-check against
the proposal's exact list before deleting). Commit:
`refactor: Settings now inherits SharedSettings (Phase 1 step 2/4)`

## Step 3 — Update the 15 video_core provider files

For each file in the proposal's Step 2 list:
```
video_core/providers/tts/edge_tts.py
video_core/providers/image/a1111.py
video_core/providers/image/huggingface.py
video_core/providers/llm/groq_provider.py
video_core/providers/image/factory.py
video_core/providers/image/gemini.py
video_core/providers/llm/openai_provider.py
video_core/providers/search/factory.py
video_core/providers/llm/factory.py
video_core/providers/llm/gemini.py
video_core/providers/search/tavily.py
video_core/providers/tts/kokoro.py
video_core/providers/tts/factory.py
video_core/providers/image/pollinations.py
video_core/providers/llm/ollama.py
```
Change `from ytfactory.config.settings import Settings` →
`from video_core.config.shared_settings import SharedSettings`, and
update the type annotation on whatever parameter/attribute held
`Settings` to `SharedSettings`. No other logic changes — confirm this
by keeping the diff to import line + annotation line per file.

Run tests after all 15. Commit:
`refactor: video_core providers depend on SharedSettings, not ytfactory.config (Phase 1 step 3/4)`

## Step 4 — Fix the flagged test patches (from Step 0's list)

Update each test identified in Step 0 to patch
`video_core.config.shared_settings.SharedSettings` instead of
`ytfactory.config.settings.Settings`, wherever the mock is consumed by
a video_core provider. Leave patches unchanged where the mock is
consumed by ytfactory-side code — `Settings` still works there via
inheritance.

Run full test suite:
```bash
uv run pytest tests/ 2>&1 | tail -5
```
Confirm 2161 passing, 0 failing (or higher if any new tests were
warranted — there shouldn't be, this is pure relocation). Commit:
`test: update Settings patches for video_core/ytfactory split (Phase 1 step 4/4)`

## Step 5 — Update layering enforcement

In `scripts/check_layering.py`, remove `ytfactory.config.settings` from
the `KNOWN_BUCKET_C` allowlist — this violation is now resolved.
`ytfactory.shared.constants` stays on the allowlist (untouched, out of
scope for this pass). Run the layering check, confirm zero violations.
Commit: `chore: remove ytfactory.config.settings from layering allowlist (resolved)`

## Final report

State: final test count, five commit hashes, confirmation that
`check_layering.py` now shows only one remaining Bucket-C exception
(`ytfactory.shared.constants`).
