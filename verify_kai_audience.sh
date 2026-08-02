#!/usr/bin/env bash
# ============================================================
# verify_kai_audience.sh
# Run from repo root: bash verify_kai_audience.sh
#
# Verifies that AUDIENCE_VISUAL_DIRECTIVE + KAI ANCHOR CHARACTER
# are correctly wired across the ytfactory pipeline.
#
# Layers:
#   L0 — New files exist
#   L1 — Prompt injections in place
#   L2 — Schema / code changes
#   L3 — Firewall wiring
#   L4 — Test suite (new tests only, fast)
# ============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0
FAIL=0
WARN=0

# ── colours ─────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✔${NC}  $1"; PASS=$((PASS + 1)); }
fail() { echo -e "  ${RED}✗${NC}  $1"; FAIL=$((FAIL + 1)); }
warn() { echo -e "  ${YELLOW}⚠${NC}  $1"; WARN=$((WARN + 1)); }
hdr()  { echo -e "\n${CYAN}${BOLD}── $1 ──${NC}"; }

# ── helper: file contains string ────────────────────────────
contains() {
  local file="$1" pattern="$2" label="$3"
  if [ ! -f "$file" ]; then
    fail "FILE NOT FOUND: $file  (needed for: $label)"
    return
  fi
  if grep -q "$pattern" "$file"; then
    ok "$label"
  else
    fail "$label  →  pattern not found: '$pattern'  in  $file"
  fi
}

# ── helper: file exists ──────────────────────────────────────
exists() {
  local file="$1" label="$2"
  if [ -f "$file" ]; then
    ok "$label"
  else
    fail "$label  →  missing: $file"
  fi
}

# ── helper: grep across src/ ────────────────────────────────
src_contains() {
  local pattern="$1" label="$2"
  if grep -rq "$pattern" src/ 2>/dev/null; then
    ok "$label"
  else
    fail "$label  →  pattern '$pattern' not found anywhere in src/"
  fi
}

# ============================================================
# L0 — NEW FILES EXIST
# ============================================================
hdr "L0 — New files"

# Prompts — agent may have put these in either location; check both
KAI_PROFILE=""
for p in \
    "src/ytfactory/prompts/KAI_PROFILE.md" \
    "src/video_core/prompts/KAI_PROFILE.md" \
    "prompts/KAI_PROFILE.md"
do
  if [ -f "$p" ]; then KAI_PROFILE="$p"; break; fi
done

if [ -n "$KAI_PROFILE" ]; then
  ok "KAI_PROFILE.md found at $KAI_PROFILE"
else
  fail "KAI_PROFILE.md not found — checked src/ytfactory/prompts/, src/video_core/prompts/, prompts/"
fi

AUDIENCE_DIRECTIVE=""
for p in \
    "src/ytfactory/prompts/AUDIENCE_VISUAL_DIRECTIVE.md" \
    "src/video_core/prompts/AUDIENCE_VISUAL_DIRECTIVE.md" \
    "prompts/AUDIENCE_VISUAL_DIRECTIVE.md"
do
  if [ -f "$p" ]; then AUDIENCE_DIRECTIVE="$p"; break; fi
done

if [ -n "$AUDIENCE_DIRECTIVE" ]; then
  ok "AUDIENCE_VISUAL_DIRECTIVE.md found at $AUDIENCE_DIRECTIVE"
else
  fail "AUDIENCE_VISUAL_DIRECTIVE.md not found"
fi

# Firewall
FIREWALL=""
for p in \
    "src/ytfactory/validators/kai_firewall.py" \
    "src/ytfactory/kai_firewall.py" \
    "src/video_core/validators/kai_firewall.py"
do
  if [ -f "$p" ]; then FIREWALL="$p"; break; fi
done

if [ -n "$FIREWALL" ]; then
  ok "kai_firewall.py found at $FIREWALL"
else
  fail "kai_firewall.py not found — checked src/ytfactory/validators/, src/ytfactory/, src/video_core/validators/"
fi

# ============================================================
# L1 — PROMPT INJECTIONS
# ============================================================
hdr "L1 — Prompt injections"

# Find ATMA_THEORY_COMPOSER.md
COMPOSER_MD=""
for p in \
    "src/ytfactory/script_enhancer/prompts/ATMA_THEORY_COMPOSER.md" \
    "src/ytfactory/composer/ATMA_THEORY_COMPOSER.md" \
    "src/ytfactory/prompts/ATMA_THEORY_COMPOSER.md" \
    "prompts/ATMA_THEORY_COMPOSER.md"
do
  if [ -f "$p" ]; then COMPOSER_MD="$p"; break; fi
done

if [ -z "$COMPOSER_MD" ]; then
  fail "ATMA_THEORY_COMPOSER.md not found — cannot check L1 composer injections"
else
  ok "ATMA_THEORY_COMPOSER.md found at $COMPOSER_MD"
  contains "$COMPOSER_MD" "VISUAL ANCHOR CHARACTER"  "Composer → VISUAL ANCHOR CHARACTER section"
  contains "$COMPOSER_MD" "CHARACTERS & EXAMPLES"    "Composer → CHARACTERS & EXAMPLES section (audience rule)"
  contains "$COMPOSER_MD" "US, UK, AU, CA"           "Composer → audience countries listed"
  contains "$COMPOSER_MD" "Kai"                      "Composer → Kai referenced in system prompt"
  contains "$COMPOSER_MD" "NEVER"                    "Composer → hard constraint present ('NEVER' keyword)"
  contains "$COMPOSER_MD" "Western"                  "Composer → Western character directive present"
fi

# Find scene planner
SCENE_PLANNER=""
for p in \
    "src/ytfactory/agents/nodes/scene_planner.py" \
    "src/ytfactory/nodes/scene_planner.py"
do
  if [ -f "$p" ]; then SCENE_PLANNER="$p"; break; fi
done

if [ -z "$SCENE_PLANNER" ]; then
  fail "scene_planner.py not found"
else
  ok "scene_planner.py found at $SCENE_PLANNER"

  # Check for inline system prompt injection OR loaded from .md file
  if grep -q "anchor_role\|ANCHOR_ROLE\|anchor role" "$SCENE_PLANNER"; then
    ok "Scene planner → anchor_role logic present in Python"
  else
    fail "Scene planner → anchor_role not referenced in scene_planner.py"
  fi

  # Check classification keywords
  contains "$SCENE_PLANNER" '"primary"'   "Scene planner → 'primary' role defined"
  contains "$SCENE_PLANNER" '"spectator"' "Scene planner → 'spectator' role defined"
  contains "$SCENE_PLANNER" '"absent"'    "Scene planner → 'absent' role defined"
fi

# Check if scene planner has a companion .md system prompt
SCENE_PLANNER_MD=""
for p in \
    "src/ytfactory/prompts/SCENE_PLANNER.md" \
    "src/ytfactory/agents/nodes/SCENE_PLANNER.md" \
    "src/ytfactory/prompts/scene_planner_system.md"
do
  if [ -f "$p" ]; then SCENE_PLANNER_MD="$p"; break; fi
done

if [ -n "$SCENE_PLANNER_MD" ]; then
  ok "Scene planner .md system prompt found at $SCENE_PLANNER_MD"
  contains "$SCENE_PLANNER_MD" "anchor_role"    "Scene planner .md → anchor_role instructions"
  contains "$SCENE_PLANNER_MD" "dark hair"      "Scene planner .md → Kai compressed spec (dark hair)"
  contains "$SCENE_PLANNER_MD" "spectator"      "Scene planner .md → spectator mode instructions"
  contains "$SCENE_PLANNER_MD" "SYMBOLIC"       "Scene planner .md → audience directive Priority 1 (symbolic)"
  contains "$SCENE_PLANNER_MD" "Western"        "Scene planner .md → audience directive Priority 2 (western)"
else
  warn "No companion .md found for scene planner — if system prompt is inline Python, L1 checks above cover it"
fi

# Check KAI_PROFILE.md content (if found)
if [ -n "$KAI_PROFILE" ]; then
  contains "$KAI_PROFILE" "primary"           "KAI_PROFILE.md → PRIMARY role defined"
  contains "$KAI_PROFILE" "spectator"         "KAI_PROFILE.md → SPECTATOR role defined"
  contains "$KAI_PROFILE" "ABSENT"            "KAI_PROFILE.md → ABSENT role defined"
  contains "$KAI_PROFILE" "dark hair"         "KAI_PROFILE.md → compressed spec present"
  contains "$KAI_PROFILE" "NEVER"             "KAI_PROFILE.md → viewer-facing firewall documented"
  contains "$KAI_PROFILE" "internal"          "KAI_PROFILE.md → internal-only flag documented"
fi

# ============================================================
# L2 — SCHEMA / CODE CHANGES
# ============================================================
hdr "L2 — Schema and code changes"

# anchor_role in Pydantic model
if grep -rq "anchor_role" src/ 2>/dev/null; then
  ok "anchor_role field found in src/ (Pydantic model or equivalent)"
  # More specific: check it's in a model file
  if grep -rq "anchor_role.*Literal\|Literal.*anchor_role\|anchor_role.*str" src/ 2>/dev/null; then
    ok "anchor_role has a type annotation in Pydantic model"
  else
    warn "anchor_role found but may not be typed — check the per-scene Pydantic model"
  fi
else
  fail "anchor_role not found anywhere in src/ — Pydantic schema not updated"
fi

# SharedSettings — new fields
SETTINGS_FILE=""
for p in \
    "src/video_core/config/shared_settings.py" \
    "src/video_core/settings.py" \
    "src/ytfactory/settings.py" \
    "src/video_core/config.py"
do
  if [ -f "$p" ]; then
    if grep -q "AUDIENCE_PROFILE\|ANCHOR_CHARACTER" "$p"; then
      SETTINGS_FILE="$p"; break
    fi
  fi
done

if [ -n "$SETTINGS_FILE" ]; then
  ok "Settings file with new fields found at $SETTINGS_FILE"
  contains "$SETTINGS_FILE" "AUDIENCE_PROFILE"          "Settings → AUDIENCE_PROFILE field"
  contains "$SETTINGS_FILE" "western_english"           "Settings → AUDIENCE_PROFILE default = 'western_english'"
  contains "$SETTINGS_FILE" "ANCHOR_CHARACTER_ENABLED"  "Settings → ANCHOR_CHARACTER_ENABLED field"
  contains "$SETTINGS_FILE" "ANCHOR_CHARACTER_ID"       "Settings → ANCHOR_CHARACTER_ID field"
  contains "$SETTINGS_FILE" "Kai"                       "Settings → ANCHOR_CHARACTER_ID = 'Kai'"
else
  fail "Settings file not found with new fields — AUDIENCE_PROFILE / ANCHOR_CHARACTER_* not added to SharedSettings"
fi

# _refine_prompt_from_score — has anchor_role parameter
PIPELINE_FILE=""
for p in \
    "src/ytfactory/images/pipeline.py" \
    "src/ytfactory/two_phase/pipeline.py" \
    "src/ytfactory/pipeline.py" \
    "src/ytfactory/build/pipeline.py"
do
  if [ -f "$p" ]; then
    if grep -q "_refine_prompt_from_score" "$p"; then
      PIPELINE_FILE="$p"; break
    fi
  fi
done

if [ -n "$PIPELINE_FILE" ]; then
  ok "_refine_prompt_from_score found in $PIPELINE_FILE"
  if grep -A5 "_refine_prompt_from_score" "$PIPELINE_FILE" | grep -q "anchor_role"; then
    ok "_refine_prompt_from_score → anchor_role parameter present"
  else
    fail "_refine_prompt_from_score → anchor_role parameter NOT added to function signature"
  fi
  if grep -q "KAI_ROLE_REFINEMENT\|anchor_role.*instruction\|role_instruction" "$PIPELINE_FILE"; then
    ok "_refine_prompt_from_score → role-specific refinement instructions present"
  else
    fail "_refine_prompt_from_score → role-specific refinement instructions NOT found"
  fi
else
  warn "_refine_prompt_from_score not located — check pipeline.py path manually"
fi

# ============================================================
# L3 — FIREWALL WIRING
# ============================================================
hdr "L3 — Firewall wiring"

if [ -n "$FIREWALL" ]; then
  contains "$FIREWALL" "KaiFirewallViolation"  "Firewall → KaiFirewallViolation exception defined"
  contains "$FIREWALL" "re.IGNORECASE"         "Firewall → case-insensitive regex"
  contains "$FIREWALL" 'KAI_PATTERN'           "Firewall → KAI_PATTERN compiled regex defined"
  contains "$FIREWALL" "check_artifact"        "Firewall → check_artifact() function defined"
  contains "$FIREWALL" "check_file"            "Firewall → check_file() function defined"
fi

# Firewall imported and called in graph/pipeline
GRAPH_FILE=$(grep -rl "kai_firewall\|KaiFirewallViolation" src/ 2>/dev/null | grep -v "kai_firewall.py" | head -1)

if [ -n "$GRAPH_FILE" ]; then
  ok "Firewall imported in $GRAPH_FILE"
  if grep -q "check_artifact\|check_file" "$GRAPH_FILE"; then
    ok "Firewall → check_artifact/check_file called in $(basename $GRAPH_FILE)"
  else
    warn "Firewall imported in $(basename $GRAPH_FILE) but check_artifact/check_file call not confirmed — verify wiring manually"
  fi
else
  # Broader fallback: check_artifact called anywhere in src/
  if grep -rq "check_artifact\|KaiFirewallViolation" src/ 2>/dev/null; then
    warn "Firewall calls found in src/ but import location unclear — run: grep -r 'kai_firewall' src/ --include='*.py' -l"
  else
    fail "Firewall not imported anywhere in src/ — check_artifact not wired"
  fi
fi

# Three wiring points: post-composer, pre-TTS, post-subtitle
echo ""
echo "  Checking three firewall wiring points..."

# Post-composer: should be near composer invocation or after it
if grep -rq "check_artifact.*script\|kai_firewall.*composer\|firewall.*composer" src/ 2>/dev/null; then
  ok "Firewall → post-composer wiring found"
else
  # Softer check: does check_artifact get called with a script-related arg anywhere?
  if grep -rq "check_artifact" src/ 2>/dev/null; then
    warn "check_artifact exists but post-composer wiring not clearly identifiable — verify manually"
  else
    fail "Firewall → post-composer wiring NOT found (check_artifact not called anywhere in src/)"
  fi
fi

# Subtitle wiring
if grep -rq "check_file.*srt\|check_file.*subtitle\|check_artifact.*subtitle\|check_artifact.*srt" src/ 2>/dev/null; then
  ok "Firewall → post-subtitle wiring found"
else
  warn "Firewall → post-subtitle wiring not clearly identifiable — verify manually that subtitles.srt is scanned"
fi

# ============================================================
# L4 — TEST SUITE (new tests only)
# ============================================================
hdr "L4 — Test suite"

echo "  Running new test files (fast, targeted)..."
echo ""

# Check test files exist
TEST_FIREWALL=""
for p in \
    "tests/test_kai_firewall.py" \
    "tests/ytfactory/test_kai_firewall.py"
do
  if [ -f "$p" ]; then TEST_FIREWALL="$p"; break; fi
done

TEST_SCENE=""
for p in \
    "tests/test_scene_planner.py" \
    "tests/ytfactory/test_scene_planner.py"
do
  if [ -f "$p" ]; then TEST_SCENE="$p"; break; fi
done

TEST_COMPOSER=""
for p in \
    "tests/test_composer.py" \
    "tests/ytfactory/test_composer.py"
do
  if [ -f "$p" ]; then TEST_COMPOSER="$p"; break; fi
done

if [ -z "$TEST_FIREWALL" ]; then
  fail "tests/test_kai_firewall.py not found — firewall tests not written"
else
  ok "test_kai_firewall.py found"
  echo ""
  echo -e "  ${CYAN}Running: uv run pytest $TEST_FIREWALL -v${NC}"
  if uv run pytest "$TEST_FIREWALL" -v 2>&1 | tail -5; then
    ok "Firewall tests passed"
  else
    fail "Firewall tests FAILED — see output above"
  fi
fi

echo ""
if [ -n "$TEST_SCENE" ]; then
  echo -e "  ${CYAN}Running: uv run pytest $TEST_SCENE -v -k 'anchor'${NC}"
  if uv run pytest "$TEST_SCENE" -v -k "anchor" 2>&1 | tail -5; then
    ok "Scene planner anchor tests passed"
  else
    fail "Scene planner anchor tests FAILED"
  fi
else
  warn "test_scene_planner.py not found — anchor_role tests not written"
fi

echo ""
if [ -n "$TEST_COMPOSER" ]; then
  echo -e "  ${CYAN}Running: uv run pytest $TEST_COMPOSER -v -k 'kai or audience'${NC}"
  if uv run pytest "$TEST_COMPOSER" -v -k "kai or audience" 2>&1 | tail -5; then
    ok "Composer kai/audience tests passed"
  else
    fail "Composer kai/audience tests FAILED"
  fi
else
  warn "test_composer.py not found or no kai/audience tests — check test coverage"
fi

# Settings test
echo ""
echo -e "  ${CYAN}Running: settings defaults quick-check (grep-based)${NC}"
SETTINGS_HITS=$(grep -r "AUDIENCE_PROFILE\|ANCHOR_CHARACTER_ENABLED\|ANCHOR_CHARACTER_ID" src/ --include="*.py" -l 2>/dev/null)
if [ -n "$SETTINGS_HITS" ]; then
  ok "Settings fields found in: $(echo $SETTINGS_HITS | tr '\n' ' ')"
  # Check default values
  if grep -rq "western_english" src/ --include="*.py" 2>/dev/null; then
    ok "Settings → AUDIENCE_PROFILE default 'western_english' present"
  else
    fail "Settings → AUDIENCE_PROFILE default 'western_english' NOT found in any .py"
  fi
  if grep -rq "ANCHOR_CHARACTER_ID.*Kai\|Kai.*ANCHOR_CHARACTER_ID" src/ --include="*.py" 2>/dev/null; then
    ok "Settings → ANCHOR_CHARACTER_ID = 'Kai' present"
  else
    fail "Settings → ANCHOR_CHARACTER_ID = 'Kai' NOT found in any .py"
  fi
else
  fail "Settings fields not found — AUDIENCE_PROFILE / ANCHOR_CHARACTER_* not added to SharedSettings"
fi

# Full existing suite — just count, don't gate on it here
echo ""
echo -e "  ${CYAN}Running full suite to check for regressions (summary only)...${NC}"
uv run pytest --tb=no -q 2>&1 | tail -3 || true

# ============================================================
# SUMMARY
# ============================================================
echo ""
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo -e "${BOLD}  VERIFICATION SUMMARY${NC}"
echo -e "${BOLD}════════════════════════════════════════${NC}"
echo -e "  ${GREEN}✔  PASSED : $PASS${NC}"
echo -e "  ${RED}✗  FAILED : $FAIL${NC}"
echo -e "  ${YELLOW}⚠  WARNS  : $WARN${NC}"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo -e "  ${RED}${BOLD}Action required — $FAIL check(s) failed.${NC}"
  echo -e "  Fix each ✗ above and re-run this script."
elif [ "$WARN" -gt 0 ]; then
  echo -e "  ${YELLOW}${BOLD}Static checks passed. Review the ⚠ warnings manually.${NC}"
  echo -e "  Then run the functional probe below."
else
  echo -e "  ${GREEN}${BOLD}All static + test checks passed.${NC}"
  echo -e "  Run the functional probe to confirm end-to-end behaviour."
fi

echo ""
echo -e "${CYAN}${BOLD}── FUNCTIONAL PROBE (run manually after this script passes) ──${NC}"
cat << 'EOF'

  1. Run Phase 1 on a short generic test script (not India-specific):
       uv run ytfactory   →  select "1. New"  →  feed a short base script

  2. After Phase 1 completes, inspect scene-plan.json:
       python - << 'PY'
import json, pathlib, sys
plan = json.loads(pathlib.Path("path/to/scene-plan.json").read_text())
scenes = plan.get("scenes", [])
roles = [s.get("anchor_role", "MISSING") for s in scenes]
print(f"Scenes: {len(scenes)}")
print(f"Roles : {roles}")
print(f"  primary   = {roles.count('primary')}")
print(f"  spectator = {roles.count('spectator')}")
print(f"  absent    = {roles.count('absent')}")
print(f"  MISSING   = {roles.count('MISSING')}")

# Check opening scene
if roles and roles[0] == "absent":
    print("WARN: Opening scene is 'absent' — Kai not established at the start")

# Spot-check primary prompts contain Kai spec
for s in scenes:
    if s.get("anchor_role") == "primary":
        prompt = s.get("visual_prompt", "").lower()
        has_kai = any(k in prompt for k in ["dark hair", "simple dark shirt", "lean young man"])
        if not has_kai:
            print(f"FAIL scene {s['scene_id']}: primary but no Kai spec in visual_prompt")
            print(f"  → {prompt[:120]}...")

# Spot-check absent prompts have no Kai spec
for s in scenes:
    if s.get("anchor_role") == "absent":
        prompt = s.get("visual_prompt", "").lower()
        if "dark hair" in prompt or "simple dark shirt" in prompt:
            print(f"WARN scene {s['scene_id']}: absent but Kai spec leaked into visual_prompt")
print("Done.")
PY

  3. Confirm 'Kai' not in script.md:
       grep -i "\bkai\b" path/to/script.md && echo "FAIL — Kai in script" || echo "PASS — Kai not in script"

  4. Confirm 'Kai' not in subtitles.srt:
       grep -i "\bkai\b" path/to/subtitles.srt && echo "FAIL" || echo "PASS"

  5. Visually inspect one PRIMARY prompt and one SPECTATOR prompt:
       python -c "
import json, pathlib
plan = json.loads(pathlib.Path('path/to/scene-plan.json').read_text())
for s in plan['scenes']:
    if s.get('anchor_role') == 'primary':
        print('PRIMARY scene', s['scene_id'], ':\n', s['visual_prompt'], '\n'); break
for s in plan['scenes']:
    if s.get('anchor_role') == 'spectator':
        print('SPECTATOR scene', s['scene_id'], ':\n', s['visual_prompt'], '\n'); break
"

EOF
echo ""