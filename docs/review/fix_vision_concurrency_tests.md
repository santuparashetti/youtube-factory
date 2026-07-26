Investigate and fix the two pre-existing failing tests surfaced during the
MOT_006 investigation (unrelated to that work, but now worth closing out):

```
tests/test_vision_concurrency.py::test_default_is_five
tests/test_vision_concurrency.py::test_semaphore_size_matches_config
```

Both assert `vision_max_concurrency == 5`, but the configured value is
currently `1`.

## Investigate first — do not just pick a fix

1. Find where `vision_max_concurrency` is defined/configured (default
   value, env var, settings file, factory-specific config override —
   check both `SharedSettings` and any factory-specific settings, per the
   Settings split from the video_core/ytfactory refactor).
2. Determine which side is actually wrong:
   - Was the default intentionally lowered to 1 at some point (e.g., due
     to VRAM/memory constraints running the local vision model —
     Qwen2.5-VL-3B via llama.cpp) and the tests were never updated to
     match?
   - Or is 1 an accidental misconfiguration, and 5 was and still is the
     intended default?
3. Check git history/blame on both the config value and the test file to
   see which changed more recently and whether there's a commit message
   or related change that explains the drop to 1 (e.g., alongside the
   Qwen2.5-VL-3B switch from MiniCPM-V 2.6, or a hardware/resource change).
4. Check if `vision_max_concurrency=1` is a deliberate current operational
   setting (e.g., for a resource-constrained environment) that should stay
   1 in practice but be configurable — in which case the fix may be to
   make the test read the actual configured value dynamically instead of
   hardcoding an expectation of 5, rather than changing the configured
   value itself.

## Report before fixing

Report which of the above is the case, with evidence (git history, config
file contents, any related comments/commit messages), before applying a
fix. Don't guess — if the history doesn't clearly explain it, say so and
recommend the safer of the two options (e.g., defaulting to whatever value
is currently in production use is usually the safer path, so as not to
silently change concurrency behavior for the running system).

## Fix

Once the correct direction is confirmed:

- If 5 should be the real default: restore it in config, and confirm
  whether the drop to 1 anywhere was a bug that could have affected
  running throughput/performance since it was introduced.
- If 1 is now correct: update the two tests to match the real current
  default/behavior instead of asserting a stale expectation of 5.
- If the actual fix is to make concurrency configurable-and-tested against
  the live config rather than a hardcoded number: implement that instead.

Then:

- Re-run the full test suite and confirm these two tests pass along with
  the rest (should return to 2602 passed / 0 unrelated failures, or
  whatever the corrected total is).
- Confirm this change doesn't affect anything already verified in the
  MOT_006 fix stream (persistence, classifier tuning, motion rebalancer) —
  it shouldn't, since it's unrelated, but confirm no interaction.

## Output format

```
## Root cause
[which side was wrong, with evidence]

## Fix applied
[config change, test change, or both — with file/line references]

## Test suite result
[pass/fail counts after fix]

## Confirmation of no interaction with MOT_006 fixes
[brief confirmation]
```
