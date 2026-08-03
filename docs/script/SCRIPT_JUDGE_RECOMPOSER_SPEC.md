# SCRIPT_JUDGE_RECOMPOSER_SPEC.md

**Version:** v1.0  
**Token budget:** Read once, implement in one pass.  
**New files:** judge.py, recomposer.py, SCRIPT_JUDGE_PROMPT.md, GUIDED_RECOMPOSER_PROMPT.md  
**Modified:** shared_settings.py, .env.example, selection.py, openai_provider.py (model override), test_composer.py  
**Do NOT touch:** TTS, Phase 2, scene_planner, editorial_qa logic, any gate scores  

---

## OVERVIEW

Two-stage addition to the A/B selection flow:

```
Composer A → QA A ──┐
Composer B → QA B ──┤→ Script Judge → verdict + section map
                     │        │
                     │   hybrid? ──yes──→ Guided Recomposer → QA + rehook
                     │        │                    │
                     │        no              fail? → fall back to winner
                     │        ↓                    ↓
                     └──→ winner                 recomposed
                              ↓
                        Human review (always — shows verdict + evidence)
```

**Fallback chain (never raises to pipeline):**
1. Recomposed script → if passes QA + rehook → use it
2. Recomposed fails → use judge winner (already passed)
3. Judge errors → use Script A (first pass, already validated)

---

## STEP 1 — MODEL OVERRIDE IN openai_provider.py

The provider currently reads `settings.LLM_MODEL` globally.
Add a `model` override parameter to `generate()`:

```python
def generate(
    self,
    system: str,
    user: str,
    temperature: float = 0.7,
    json_mode: bool = False,
    model: Optional[str] = None,          # ← ADD THIS
) -> str:
    effective_model = model or settings.LLM_MODEL
    # use effective_model everywhere LLM_MODEL was previously referenced
```

This is the only change to openai_provider.py. No other callers need updating
(they pass no model arg → fall back to settings.LLM_MODEL as before).

---

## STEP 2 — SETTINGS

In `src/video_core/config/shared_settings.py`, add under the COMPOSER block:

```python
# Script Judge + Guided Recomposer
SCRIPT_JUDGE_ENABLED: bool = True
SCRIPT_JUDGE_MODEL: str = "deepseek/deepseek-v3.2"
GUIDED_RECOMPOSE_ENABLED: bool = True
GUIDED_RECOMPOSER_MODEL: str = "deepseek/deepseek-v3.2"
```

In `.env.example`, add:

```
# Script Judge + Guided Recomposer
# Override to use a better model for high-stakes script quality decisions.
# Any OpenRouter model string is valid (e.g. anthropic/claude-opus-4,
# openai/gpt-4o, google/gemini-2.5-pro). Defaults to the main LLM_MODEL.
SCRIPT_JUDGE_ENABLED=true
SCRIPT_JUDGE_MODEL=deepseek/deepseek-v3.2
GUIDED_RECOMPOSE_ENABLED=true
GUIDED_RECOMPOSER_MODEL=deepseek/deepseek-v3.2
```

**Note to implementer:** Santosh will set these to a premium model in his local `.env`
for production runs. The defaults keep existing behaviour when not configured.

---

## STEP 3 — PROMPT FILES

### 3a. `src/ytfactory/prompts/SCRIPT_JUDGE_PROMPT.md`

```
You are a senior documentary script editor with deep expertise in philosophical
storytelling, narrative structure, and voice consistency.

You are given two versions of the same documentary script (Script A and Script B),
both written for a philosophical YouTube channel called Atma Theory. Your task is
to evaluate them and produce a verdict.

EVALUATION CRITERIA (in priority order):
1. Opening hook — which script creates stronger immediate curiosity and emotional pull?
2. Voice consistency — which reads as one continuous, unbroken voice throughout?
3. Story and example quality — which uses more specific, resonant, earned examples?
4. Philosophical depth — which carries a more substantive idea beneath the surface?
5. Ending impact — which closes with greater emotional and intellectual weight?
6. Rehook quality — which more naturally echoes the opening in the closing?
7. Overall arc — which has a more satisfying emotional journey from start to finish?

SECTION IDENTIFICATION:
First, identify the natural narrative sections in the scripts (they will largely overlap).
Common sections: opening hook, first analogy, core argument, examples/stories, climax
moment, closing reframe, ending. Use the actual content, not these labels.

OUTPUT: Respond ONLY with valid JSON. No preamble. No markdown fences.

{
  "script_a_score": <float 1-10, one decimal>,
  "script_b_score": <float 1-10, one decimal>,
  "winner": <"A" | "B">,
  "hybrid_recommended": <true | false>,
  "sections": [
    {
      "name": "<natural section name>",
      "winner": <"A" | "B">,
      "evidence": "<quoted phrase from the winning script — under 20 words>",
      "reason": "<one sentence: why this version handles this beat better>"
    }
  ],
  "hybrid_rationale": "<two sentences max: what makes each script stronger in its
    domain, and why combining them would outperform either>",
  "verdict_summary": "<one sentence: the final editorial recommendation>"
}

hybrid_recommended must be true ONLY when the scripts differ meaningfully in their
strongest sections — when Script A clearly wins some beats and Script B clearly wins
others. If one script dominates in all or nearly all sections, set hybrid_recommended
to false and declare a clean winner. Do not recommend a hybrid out of politeness.
```

### 3b. `src/ytfactory/prompts/GUIDED_RECOMPOSER_PROMPT.md`

```
You are a master documentary writer. You are given two versions of the same script
(Script A and Script B) and a section map identifying which script handles each
narrative beat more effectively.

Your task: write a single new whole-cloth script that incorporates the best of both.

CRITICAL RULES:
1. Write as ONE continuous voice from the first word to the last. This is a composition
   task, not an assembly task. Do not stitch or paste sections together.
2. Use the section map as creative guidance, not as a cutting plan. Let the stronger
   version's approach to each beat INFORM your writing — do not copy it verbatim.
3. Every sentence must flow naturally from the sentence before it. Read your draft
   aloud mentally. If a transition feels abrupt, rewrite it.
4. Preserve the opening hook from whichever script the section map designates as
   stronger for the opening — this is the highest-leverage line.
5. Preserve the ending from whichever script the section map designates as stronger
   for the ending — this is the second highest-leverage line.
6. The total length must stay within 10% of the average word count of the two scripts.
7. The script MUST include a rehook: a closing line (before the brand card) that
   directly echoes a specific image or phrase from the opening hook.
8. End with exactly three lines: "This is Atma Theory." / "If these ideas resonate
   with you, join us on this journey." / "Clear mind. Meaningful life."

OUTPUT: The recomposed script only. No preamble, no explanation, no labels.
```

---

## STEP 4 — judge.py

Create `src/ytfactory/composer/judge.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel, Field

from video_core.config.shared_settings import settings
from video_core.providers.llm.openai_provider import OpenAIProvider


# ── Output models ────────────────────────────────────────────────────────────

class SectionVerdict(BaseModel):
    name: str
    winner: Literal["A", "B"]
    evidence: str
    reason: str


class JudgeVerdict(BaseModel):
    script_a_score: float = Field(ge=1.0, le=10.0)
    script_b_score: float = Field(ge=1.0, le=10.0)
    winner: Literal["A", "B"]
    hybrid_recommended: bool
    sections: list[SectionVerdict]
    hybrid_rationale: str
    verdict_summary: str


# ── Public function ───────────────────────────────────────────────────────────

def judge_scripts(
    script_a: str,
    script_b: str,
    provider: OpenAIProvider,
) -> Optional[JudgeVerdict]:
    """
    Calls the judge model and returns a JudgeVerdict.
    Returns None on any failure — caller falls back to Script A.
    """
    if not settings.SCRIPT_JUDGE_ENABLED:
        logger.info("Script judge disabled — skipping.")
        return None

    prompt = _load_prompt("SCRIPT_JUDGE_PROMPT.md")

    user_content = (
        f"SCRIPT A:\n\n{script_a}\n\n"
        f"---\n\n"
        f"SCRIPT B:\n\n{script_b}"
    )

    try:
        raw = provider.generate(
            system=prompt,
            user=user_content,
            temperature=0.2,   # low — this is evaluation, not generation
            model=settings.SCRIPT_JUDGE_MODEL,
        )
        data = json.loads(raw.strip())
        verdict = JudgeVerdict(**data)
        logger.info(
            f"Judge verdict: A={verdict.script_a_score} B={verdict.script_b_score} "
            f"winner={verdict.winner} hybrid={verdict.hybrid_recommended}"
        )
        return verdict
    except Exception as e:
        logger.warning(f"Script judge failed ({type(e).__name__}: {e}) — will use Script A.")
        return None


def _load_prompt(filename: str) -> str:
    """Load from src/ytfactory/prompts/. Match existing prompt loader pattern."""
    from pathlib import Path
    prompt_dir = Path(__file__).parent.parent / "prompts"
    return (prompt_dir / filename).read_text(encoding="utf-8")
```

---

## STEP 5 — recomposer.py

Create `src/ytfactory/composer/recomposer.py`:

```python
from __future__ import annotations

from typing import Optional

from loguru import logger

from video_core.config.shared_settings import settings
from video_core.providers.llm.openai_provider import OpenAIProvider
from ytfactory.composer.judge import JudgeVerdict
from ytfactory.composer.pipeline import _validate_rehook_present, ComposerRehookMissingError


def guided_recompose(
    script_a: str,
    script_b: str,
    verdict: JudgeVerdict,
    provider: OpenAIProvider,
) -> Optional[str]:
    """
    Writes a new whole-cloth script guided by the judge's section map.
    Returns the recomposed script text, or None on failure.
    Caller is responsible for falling back to the judge winner.
    """
    if not settings.GUIDED_RECOMPOSE_ENABLED:
        logger.info("Guided recomposer disabled — skipping.")
        return None

    prompt = _load_prompt("GUIDED_RECOMPOSER_PROMPT.md")

    # Build the section map for the recomposer
    section_lines = "\n".join(
        f"- {s.name}: Script {s.winner} is stronger ({s.reason})"
        for s in verdict.sections
    )

    user_content = (
        f"SECTION MAP (use as guidance, not as a cut list):\n{section_lines}\n\n"
        f"SCRIPT A:\n\n{script_a}\n\n"
        f"---\n\n"
        f"SCRIPT B:\n\n{script_b}"
    )

    try:
        recomposed = provider.generate(
            system=prompt,
            user=user_content,
            temperature=0.5,   # moderate — needs creativity but constrained
            model=settings.GUIDED_RECOMPOSER_MODEL,
        )
    except Exception as e:
        logger.warning(f"Recomposer LLM call failed ({type(e).__name__}: {e}).")
        return None

    # Validate rehook before returning
    try:
        if not _validate_rehook_present(recomposed):
            raise ComposerRehookMissingError("Recomposed script missing rehook.")
    except ComposerRehookMissingError as e:
        logger.warning(f"Recomposed script failed rehook validation: {e}")
        return None

    logger.info("Guided recomposition succeeded and passed rehook validation.")
    return recomposed


def _load_prompt(filename: str) -> str:
    from pathlib import Path
    prompt_dir = Path(__file__).parent.parent / "prompts"
    return (prompt_dir / filename).read_text(encoding="utf-8")
```

---

## STEP 6 — WIRE INTO selection.py

Replace the current A/B selection logic in `selection.py` with the full flow.
Preserve the existing graceful degradation for Script B rehook failure.

```python
from ytfactory.composer.judge import judge_scripts, JudgeVerdict
from ytfactory.composer.recomposer import guided_recompose


def run_composer_with_ab_selection(
    composer,
    project_id: str,
    base_script_text: str,
) -> str:
    provider = composer.provider   # adjust to match actual provider access pattern

    # ── Generate Script A ────────────────────────────────────────────────────
    composer.run(project_id, script_text=base_script_text)
    script_a_path = script_dir / "script-a.md"
    script_a_path.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")
    script_a = script_a_path.read_text(encoding="utf-8")

    # ── Generate Script B (graceful degradation) ─────────────────────────────
    script_b: Optional[str] = None
    try:
        composer.run(project_id, script_text=base_script_text)
        script_b_path = script_dir / "script-b.md"
        script_b_path.write_text(script_file.read_text(encoding="utf-8"), encoding="utf-8")
        script_b = script_b_path.read_text(encoding="utf-8")
    except ComposerRehookMissingError as e:
        logger.warning(f"Script B failed rehook — will judge/use Script A only.\n{e}")
        console.print("[yellow]Script B failed validation — proceeding with Script A.[/yellow]")

    # If no Script B, skip judging
    if script_b is None:
        _write_final(script_a, script_file)
        return script_a

    # ── Judge ────────────────────────────────────────────────────────────────
    verdict: Optional[JudgeVerdict] = judge_scripts(script_a, script_b, provider)

    if verdict is None:
        # Judge failed entirely — use Script A as safe default
        logger.warning("Judge returned None — using Script A.")
        _write_final(script_a, script_file)
        return script_a

    # ── Log verdict for human review ─────────────────────────────────────────
    _log_verdict(verdict, script_a, script_b)

    # ── Determine output ─────────────────────────────────────────────────────
    winner_text = script_a if verdict.winner == "A" else script_b

    if verdict.hybrid_recommended:
        recomposed = guided_recompose(script_a, script_b, verdict, provider)
        if recomposed is not None:
            _write_final(recomposed, script_file)
            _write_judge_report(verdict, project_id, outcome="recomposed")
            return recomposed
        else:
            logger.warning("Recomposer failed or skipped — falling back to judge winner.")

    _write_final(winner_text, script_file)
    _write_judge_report(verdict, project_id, outcome=f"winner_{verdict.winner}")
    return winner_text


def _write_final(text: str, script_file: Path) -> None:
    script_file.write_text(text, encoding="utf-8")


def _write_judge_report(verdict: JudgeVerdict, project_id: str, outcome: str) -> None:
    """
    Write judge-report.json to the project workspace for human review.
    Include: scores, winner, hybrid_recommended, sections, outcome.
    """
    from pathlib import Path
    import json
    report_path = Path("workspace/jobs") / project_id / "judge-report.json"
    report_path.write_text(
        json.dumps({
            "outcome": outcome,
            **verdict.model_dump(),
        }, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Judge report written: {report_path}")


def _log_verdict(verdict: JudgeVerdict, script_a: str, script_b: str) -> None:
    """Print a readable verdict summary to the console."""
    from rich.console import Console
    from rich.table import Table
    c = Console()
    c.print(f"\n[bold]Script Judge Verdict[/bold]")
    c.print(f"  Script A: {verdict.script_a_score}/10")
    c.print(f"  Script B: {verdict.script_b_score}/10")
    c.print(f"  Winner: Script {verdict.winner}")
    c.print(f"  Hybrid recommended: {verdict.hybrid_recommended}")
    c.print(f"  {verdict.verdict_summary}\n")
```

**Note to implementer:** The above is pseudocode for the logic — adapt it to match the
actual variable names in the existing selection.py (script_dir, script_file, etc.).
Do not change the function signature of `run_composer_with_ab_selection`.

---

## STEP 7 — HUMAN REVIEW PRESENTATION

The existing `human_review_final_script` node presents `script.md` + QA report.
Add the judge report to this presentation when it exists:

In the human review node, after loading the script, add:

```python
judge_report_path = project_workspace / "judge-report.json"
if judge_report_path.exists():
    import json
    report = json.loads(judge_report_path.read_text())
    # Display: outcome, scores, winner, verdict_summary, hybrid_rationale
    # Display: section table (name | winner | reason)
    # This gives Santosh full transparency on what the judge decided and why
```

Display format: Rich table for sections, plain text for scores and verdict.
The human review gate must NOT be skippable when outcome == "recomposed" — 
a recomposed script always requires human eyes before proceeding.

Implement this guard:

```python
if report.get("outcome") == "recomposed" and auto_mode:
    logger.warning(
        "Auto-mode disabled for recomposed scripts — human review required."
    )
    # Force the review prompt regardless of --auto flag
```

---

## STEP 8 — TESTS

Add to `tests/test_composer.py`:

**Judge tests:**
1. `test_judge_returns_verdict_on_valid_json()` — mock provider returns valid JSON → JudgeVerdict parsed correctly
2. `test_judge_returns_none_on_json_parse_failure()` — mock returns garbage → None returned, no raise
3. `test_judge_returns_none_on_provider_exception()` — mock raises → None returned, no raise
4. `test_judge_disabled_returns_none()` — SCRIPT_JUDGE_ENABLED=False → None without calling provider
5. `test_judge_does_not_recommend_hybrid_when_one_dominates()` — assert hybrid_recommended=False respected in downstream selection (mock judge returns hybrid_recommended=False → winner used directly)

**Recomposer tests:**
6. `test_recomposer_returns_text_on_success()` — mock provider returns valid script with rehook → text returned
7. `test_recomposer_returns_none_on_missing_rehook()` — mock returns script with no rehook → None returned
8. `test_recomposer_returns_none_on_provider_exception()` — mock raises → None returned
9. `test_recomposer_disabled_returns_none()` — GUIDED_RECOMPOSE_ENABLED=False → None without calling provider

**Integration / selection tests:**
10. `test_selection_uses_recomposed_when_hybrid_recommended()` — full mock: judge says hybrid → recomposer succeeds → recomposed text returned
11. `test_selection_falls_back_to_winner_when_recomposer_fails()` — judge says hybrid → recomposer returns None → winner text returned
12. `test_selection_uses_winner_when_hybrid_not_recommended()` — judge says winner=B, no hybrid → script_b returned directly
13. `test_selection_skips_judge_when_script_b_missing()` — script_b is None (rehook failure) → judge never called, script_a returned
14. `test_auto_mode_forced_off_for_recomposed_script()` — outcome=recomposed + auto=True → review gate not skipped

---

## STEP 9 — DO NOT IMPLEMENT

- LLM-based rehook quality assessment (heuristic sufficient)
- Any change to editorial_qa checks or scoring
- Any change to the PRE_RENDER_GATE threshold or score calculation
- Automatic application of judge verdict without human review on recomposed output
- Streaming or async LLM calls (sync is fine for this use case)
- Any UI change beyond the judge report display in human review

---

## CONFIGURATION REFERENCE (for Santosh's .env)

```
# To use a premium model for script quality decisions only:
SCRIPT_JUDGE_MODEL=anthropic/claude-opus-4
GUIDED_RECOMPOSER_MODEL=anthropic/claude-opus-4

# To use GPT-4o:
SCRIPT_JUDGE_MODEL=openai/gpt-4o
GUIDED_RECOMPOSER_MODEL=openai/gpt-4o

# To disable (A/B reverts to Script A on B failure, no judging):
SCRIPT_JUDGE_ENABLED=false
GUIDED_RECOMPOSE_ENABLED=false
```

All models must be available via the existing OpenRouter proxy configuration.
No other env changes are needed.

---

*End of SCRIPT_JUDGE_RECOMPOSER_SPEC.md*
