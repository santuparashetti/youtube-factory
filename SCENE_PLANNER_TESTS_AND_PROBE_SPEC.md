# Task: Scene Planner Anchor_Role Tests + Phase 1 Probe CLI Command

## Context

The ytfactory pipeline has a Kai anchor character system implemented per
`KAI_ANCHOR_CHARACTER_SPEC.md`. The scene planner assigns
`anchor_role: Literal["primary", "spectator", "absent"]` to each scene
in `scene-plan.json` at inference time. Everything is wired and verified
statically (47/47 checks pass in `verify_kai_audience.sh`).

Two things remain:

1. **Unit tests for scene planner anchor_role** — the spec defined them,
   the agent that implemented the spec did not write them.
   Warning in `verify_kai_audience.sh`: `test_scene_planner.py not found`.

2. **A `probe` CLI command** — to inspect a real Phase 1 run's
   `scene-plan.json` and confirm the LLM is classifying scenes correctly.
   Currently this requires running manual Python snippets; make it a
   proper `uv run ytfactory probe <project-dir>` command instead.

Do not modify any existing pipeline code. No new dependencies.
Follow existing code style throughout.

---

## Task 1: `tests/test_scene_planner.py`

Write anchor_role unit tests. Look at existing test files in `tests/`
to match class structure, fixture patterns, and how LLM calls are mocked.

The per-scene Pydantic model has:
```python
anchor_role: Literal["primary", "spectator", "absent"] = "absent"
```

The scene planner builds a `visual_prompt` per scene and sets `anchor_role`
based on script content. Mock the LLM to return controlled scene-plan JSON
so tests are deterministic.

### Required test cases

**Schema / defaults:**
- Every scene in scene-plan.json has `anchor_role` as a valid value
  (`"primary"`, `"spectator"`, or `"absent"`)
- When `anchor_role` is absent from raw JSON, the Pydantic default
  resolves to `"absent"` (not None, not missing)

**Opening scene:**
- The first scene in a typical script output is NOT `"absent"` — Kai
  should be established early (primary or spectator)

**PRIMARY role — visual_prompt contract:**
- A `primary` scene's `visual_prompt` contains at least one Kai
  compressed spec marker:
  `["dark hair", "simple dark shirt", "lean young man", "light stubble"]`
- A `primary` scene's `visual_prompt` does NOT contain the literal
  string `"Kai"` (case-insensitive)

**SPECTATOR role — visual_prompt contract:**
- A `spectator` scene's `visual_prompt` contains a brief Kai descriptor
  (check for at least one of: `"watching"`, `"dark hair"`, `"edge"`,
  `"periphery"`)
- A `spectator` scene's `visual_prompt` does NOT contain the literal
  string `"Kai"` (case-insensitive)

**ABSENT role — visual_prompt contract:**
- An `absent` scene's `visual_prompt` contains NONE of the Kai
  compressed spec markers
- An `absent` scene's `visual_prompt` does NOT contain `"Kai"`

**Global:**
- No `visual_prompt` across any scene in the output contains the
  literal string `"Kai"` (case-insensitive) — belt-and-suspenders
  complement to the firewall tests

Run with: `uv run pytest tests/test_scene_planner.py -v`
Must pass with 0 failures.

---

## Task 2: `probe` CLI command

### Where to add it

Find the existing Typer CLI entry point (likely `src/ytfactory/cli.py`
or wherever the `uv run ytfactory` commands are defined). Add a `probe`
subcommand there. Do not create a new CLI file unless the existing
pattern clearly separates commands into modules.

### Command signature

```
uv run ytfactory probe <project-dir>
```

`project-dir` is the path to a Phase 1 output directory — the one that
contains `scene-plan.json`.

### What the command must do

1. Load `<project-dir>/scene-plan.json`. If the file does not exist,
   print a clear error and exit 1.

2. Print a structured report in this format (adapt spacing/icons to
   match the project's existing CLI output style):

```
── Scene Plan Probe: <project-dir> ──

Scenes : <total>

anchor_role distribution:
  primary   : <n>  (<pct>%)
  spectator : <n>  (<pct>%)
  absent    : <n>  (<pct>%)
  MISSING   : <n>            ← if > 0, this is a FAIL

Checks:
  ✔/✗  All scenes have anchor_role field
  ✔/✗  Opening scene is not 'absent'   → actual: <role>
  ✔/✗  Closing scene is 'primary'      → actual: <role>
  ✔/✗  All primary prompts contain Kai spec markers
  ✔/✗  All absent prompts are Kai-free
  ✔/✗  No visual_prompt contains the string 'Kai'

── Samples ──

PRIMARY  (scene <id>):
  <visual_prompt, first 250 chars>

SPECTATOR (scene <id>):       ← omit section if no spectator scenes
  <visual_prompt, first 250 chars>

ABSENT (scene <id>):
  <visual_prompt, first 250 chars>

── Result: PASS / FAIL ──
```

3. Exit code:
   - `0` if all checks pass
   - `1` if any check fails (MISSING anchor_roles, Kai leaked into
     prompts, opening scene absent, etc.)

### Kai spec markers to check (same as test_scene_planner.py)

```python
KAI_MARKERS = ["dark hair", "simple dark shirt", "lean young man", "light stubble"]
```

A `primary` scene's `visual_prompt` must contain at least one.
An `absent` scene's `visual_prompt` must contain none.

### Closing scene definition

The closing scene is the last scene whose `anchor_role` is NOT
`"absent"` and that is not a brand-card/asset scene (check for
whatever flag the scene model uses for brand card — likely
`is_asset`, `scene_type`, or similar). If no such distinction
exists, use the second-to-last scene (brand card is typically last).
Look at the existing scene model to find the right field.

---

## Verification

After implementing both tasks:

```bash
# Tests
uv run pytest tests/test_scene_planner.py -v

# CLI smoke test (use any existing Phase 1 output directory)
uv run ytfactory probe /path/to/any/phase1/project/dir

# Full suite — must not regress
uv run pytest --tb=short -q
```

The `verify_kai_audience.sh` warning
`⚠ test_scene_planner.py not found` must resolve to a passing run
after this is implemented.
