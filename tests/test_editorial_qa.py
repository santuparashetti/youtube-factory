"""Tests for the Editorial QA Stage (see EDITORIAL_QA_STAGE_SPEC.md).

No live LLM calls. The eagle-script fixture uses a mocked reviewer response
crafted to reflect that script's real content, verifying the PIPELINE
correctly parses/persists/ledgers it — not live model judgment quality.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.editorial_qa.ledger import QALedger
from ytfactory.editorial_qa.pipeline import (
    FLAGGED_PENALTY,
    INVALID_PENALTY,
    EditorialQAPipeline,
    _derive_editorial_score,
    _is_flagged,
    _parse_json_response,
    _validate_evidence,
)
from ytfactory.editorial_qa.promoter import PatternPromoter, _gather_evidence_examples

EAGLE_SCRIPT_PATH = (
    Path(__file__).parent.parent
    / "base_scripts"
    / "refined script files"
    / "word-for-those-who-say-cant-do-anything.md"
)


def _make_response(text: str) -> MagicMock:
    r = MagicMock()
    r.text = text
    return r


def _qa_report_response(checks: dict, editorial_score: float = 8.0) -> str:
    return json.dumps({"checks": checks, "editorial_score": editorial_score})


@pytest.fixture
def settings():
    s = MagicMock()
    s.editorial_qa_enabled = True
    s.qa_promote_n = 4
    s.qa_promote_m = 5
    s.qa_promote_cooldown_runs = 5
    s.qa_callback_required = False
    return s


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def pipeline(settings, mock_llm):
    with patch("ytfactory.editorial_qa.pipeline.get_llm_provider", return_value=mock_llm):
        return EditorialQAPipeline(settings)


# ── Layer 1: per-check evidence validation + flag logic ─────────────────────


class TestValidateEvidenceAndFlags:
    """Per spec's testing section: each check fires on a script that needs
    it, stays clean on one that doesn't, and returns INVALID with no cited
    evidence — for all six checks."""

    # 1. ending_vs_opening
    def test_ending_vs_opening_flags_when_weaker(self):
        check = {"verdict": "weaker", "opening_beat": "A bird built a nest.", "closing_beat": "The end.", "note": "n"}
        assert _validate_evidence("ending_vs_opening", check) is True
        assert _is_flagged("ending_vs_opening", check) is True

    def test_ending_vs_opening_clean_when_stronger(self):
        check = {"verdict": "stronger", "opening_beat": "A bird built a nest.", "closing_beat": "The eagle soared free.", "note": "n"}
        assert _validate_evidence("ending_vs_opening", check) is True
        assert _is_flagged("ending_vs_opening", check) is False

    def test_ending_vs_opening_invalid_without_evidence(self):
        check = {"verdict": "weaker", "opening_beat": "", "closing_beat": "", "note": ""}
        assert _validate_evidence("ending_vs_opening", check) is False

    # 2. every_story_earns_place
    def test_every_story_flags_duplicate(self):
        check = {
            "stories": [
                {"name": "Bhagiratha", "function": "persevered against impossible odds", "duplicate_of": None},
                {"name": "Watchmaker", "function": "persevered against impossible odds", "duplicate_of": "Bhagiratha"},
            ],
            "note": "n",
        }
        assert _validate_evidence("every_story_earns_place", check) is True
        assert _is_flagged("every_story_earns_place", check) is True

    def test_every_story_clean_when_unique(self):
        check = {
            "stories": [
                {"name": "Bhagiratha", "function": "persevered against impossible odds", "duplicate_of": None},
                {"name": "Vinoba Bhave", "function": "mastery of small things enables greatness", "duplicate_of": None},
            ],
            "note": "n",
        }
        assert _validate_evidence("every_story_earns_place", check) is True
        assert _is_flagged("every_story_earns_place", check) is False

    def test_every_story_invalid_when_empty(self):
        check = {"stories": [], "note": ""}
        assert _validate_evidence("every_story_earns_place", check) is False

    # 3. unnecessary_explanation
    def test_unnecessary_explanation_flags_violations(self):
        check = {"verdict": "2", "violations": ["This means suffering is real.", "In other words, it hurts."], "note": "n"}
        assert _validate_evidence("unnecessary_explanation", check) is True
        assert _is_flagged("unnecessary_explanation", check) is True

    def test_unnecessary_explanation_clean(self):
        check = {"verdict": "clean", "violations": [], "note": "No over-explaining found."}
        assert _validate_evidence("unnecessary_explanation", check) is True
        assert _is_flagged("unnecessary_explanation", check) is False

    def test_unnecessary_explanation_invalid_when_claimed_but_uncited(self):
        check = {"verdict": "2", "violations": [], "note": ""}
        assert _validate_evidence("unnecessary_explanation", check) is False

    # 4. callback_to_opening
    def test_callback_flags_when_no(self):
        check = {"verdict": "no", "opening_image": "A bird built a nest.", "ending_quote": "This is Atma Theory.", "note": "n"}
        assert _validate_evidence("callback_to_opening", check) is True
        assert _is_flagged("callback_to_opening", check) is True

    def test_callback_clean_when_yes(self):
        check = {"verdict": "yes", "opening_image": "A bird built a nest.", "ending_quote": "Even a small bird can soar.", "note": "n"}
        assert _validate_evidence("callback_to_opening", check) is True
        assert _is_flagged("callback_to_opening", check) is False

    def test_callback_invalid_without_evidence(self):
        check = {"verdict": "no", "opening_image": "", "ending_quote": "", "note": ""}
        assert _validate_evidence("callback_to_opening", check) is False

    # 5. sounds_translated
    def test_sounds_translated_flags(self):
        check = {"verdict": "1", "flagged": ["Today's question is, why do we suffer?"], "note": "n"}
        assert _validate_evidence("sounds_translated", check) is True
        assert _is_flagged("sounds_translated", check) is True

    def test_sounds_translated_clean(self):
        check = {"verdict": "clean", "flagged": [], "note": "Reads as originally written."}
        assert _validate_evidence("sounds_translated", check) is True
        assert _is_flagged("sounds_translated", check) is False

    def test_sounds_translated_invalid_when_claimed_but_uncited(self):
        check = {"verdict": "1", "flagged": [], "note": ""}
        assert _validate_evidence("sounds_translated", check) is False

    # 6. open_loop_payoff
    def test_open_loop_payoff_flags_never_resolved(self):
        check = {"verdict": "never resolved", "question": "Where is such strength in me?", "resolution": "", "note": "n"}
        assert _validate_evidence("open_loop_payoff", check) is True
        assert _is_flagged("open_loop_payoff", check) is True

    def test_open_loop_payoff_flags_paid_off_early(self):
        check = {"verdict": "paid off early", "question": "Where is such strength in me?", "resolution": "Answered in paragraph two.", "note": "n"}
        assert _is_flagged("open_loop_payoff", check) is True

    def test_open_loop_payoff_clean_when_paid_off(self):
        check = {"verdict": "paid off", "question": "Where is such strength in me?", "resolution": "The eagle soared at the end.", "note": "n"}
        assert _validate_evidence("open_loop_payoff", check) is True
        assert _is_flagged("open_loop_payoff", check) is False

    def test_open_loop_payoff_invalid_without_evidence(self):
        check = {"verdict": "never resolved", "question": "", "resolution": "", "note": ""}
        assert _validate_evidence("open_loop_payoff", check) is False


class TestDeriveEditorialScore:
    """editorial_score is now code-derived, never model-emitted — the model
    reliably inverted the sign (production bug: -9.2, and -1.0/-9.5 even
    after prompt strengthening). Flag-count arithmetic: start at 10.0,
    subtract FLAGGED_PENALTY per flagged check, INVALID_PENALTY per invalid
    check, clamp to [0, 10]. Never negative, never model-dependent."""

    def _checks(self, **overrides) -> dict:
        base = {name: {"flagged": False, "invalid": False} for name in (
            "ending_vs_opening", "every_story_earns_place", "unnecessary_explanation",
            "callback_to_opening", "sounds_translated", "open_loop_payoff",
        )}
        for name, state in overrides.items():
            base[name] = state
        return base

    def test_zero_flags_scores_ten(self):
        assert _derive_editorial_score(self._checks()) == 10.0

    def test_one_flagged_check_subtracts_flagged_penalty(self):
        checks = self._checks(sounds_translated={"flagged": True, "invalid": False})
        assert _derive_editorial_score(checks) == 10.0 - FLAGGED_PENALTY

    def test_one_invalid_check_subtracts_invalid_penalty(self):
        checks = self._checks(sounds_translated={"flagged": False, "invalid": True})
        assert _derive_editorial_score(checks) == 10.0 - INVALID_PENALTY

    def test_invalid_weighs_more_than_flagged(self):
        flagged_only = self._checks(sounds_translated={"flagged": True, "invalid": False})
        invalid_only = self._checks(sounds_translated={"flagged": False, "invalid": True})
        assert _derive_editorial_score(invalid_only) < _derive_editorial_score(flagged_only)

    def test_multiple_flags_accumulate(self):
        checks = self._checks(
            sounds_translated={"flagged": True, "invalid": False},
            unnecessary_explanation={"flagged": True, "invalid": False},
        )
        assert _derive_editorial_score(checks) == 10.0 - 2 * FLAGGED_PENALTY

    def test_all_invalid_clamps_to_zero_not_negative(self):
        checks = {name: {"flagged": False, "invalid": True} for name in (
            "ending_vs_opening", "every_story_earns_place", "unnecessary_explanation",
            "callback_to_opening", "sounds_translated", "open_loop_payoff",
        )}
        # 6 * INVALID_PENALTY (2.0) = 12.0 > 10.0 start -> must clamp, never negative.
        assert _derive_editorial_score(checks) == 0.0

    def test_all_flagged_stays_in_range(self):
        checks = {name: {"flagged": True, "invalid": False} for name in (
            "ending_vs_opening", "every_story_earns_place", "unnecessary_explanation",
            "callback_to_opening", "sounds_translated", "open_loop_payoff",
        )}
        score = _derive_editorial_score(checks)
        assert 0.0 <= score <= 10.0

    def test_never_negative_never_model_dependent(self):
        """The score is pure arithmetic over checks — no model output involved."""
        import inspect

        assert "raw" not in inspect.signature(_derive_editorial_score).parameters
        for name in ("ending_vs_opening", "every_story_earns_place"):
            checks = self._checks(**{name: {"flagged": True, "invalid": True}})
            assert _derive_editorial_score(checks) >= 0.0


class TestParseJsonResponse:
    def test_handles_markdown_fences(self):
        assert _parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}

    def test_returns_empty_on_invalid(self):
        assert _parse_json_response("not json") == {}


# ── Layer 1: pipeline integration ────────────────────────────────────────────


class TestEditorialQAPipeline:
    def _all_clean_checks(self) -> dict:
        return {
            "ending_vs_opening": {"verdict": "stronger", "opening_beat": "o", "closing_beat": "c", "note": "n"},
            "every_story_earns_place": {"verdict": "clean", "stories": [{"name": "A", "function": "f", "duplicate_of": None}], "note": "n"},
            "unnecessary_explanation": {"verdict": "clean", "violations": [], "note": "n"},
            "callback_to_opening": {"verdict": "yes", "opening_image": "o", "ending_quote": "e", "note": "n"},
            "sounds_translated": {"verdict": "clean", "flagged": [], "note": "n"},
            "open_loop_payoff": {"verdict": "paid off", "question": "q", "resolution": "r", "note": "n"},
        }

    def test_disabled_is_full_noop(self, mock_llm, tmp_path):
        settings = MagicMock()
        settings.editorial_qa_enabled = False
        with patch("ytfactory.editorial_qa.pipeline.get_llm_provider", return_value=mock_llm):
            pipeline = EditorialQAPipeline(settings)
        with patch("ytfactory.editorial_qa.pipeline.WORKSPACE_DIR", str(tmp_path)):
            result = pipeline.run("proj-disabled", script_text="Some script.")
        assert result == {}
        mock_llm.generate.assert_not_called()
        assert not (tmp_path / "proj-disabled" / "qa").exists()

    def test_writes_report_and_ledger(self, pipeline, mock_llm, tmp_path):
        mock_llm.generate.return_value = _make_response(_qa_report_response(self._all_clean_checks()))
        ledger_path = tmp_path / "editorial_qa" / "ledger.jsonl"

        with patch("ytfactory.editorial_qa.pipeline.WORKSPACE_DIR", str(tmp_path / "jobs")):
            with patch("ytfactory.editorial_qa.ledger._DEFAULT_LEDGER_PATH", ledger_path):
                with patch("ytfactory.editorial_qa.promoter._DEFAULT_STATE_PATH", tmp_path / "editorial_qa" / "promotions.json"):
                    with patch("ytfactory.editorial_qa.promoter._DEFAULT_QA_ROOT", tmp_path / "jobs"):
                        with patch("ytfactory.editorial_qa.promoter.get_llm_provider", return_value=MagicMock()):
                            report = pipeline.run("proj-001", script_text="Some script.")

        assert report["invalid_checks"] == []
        assert all(not c["flagged"] for c in report["checks"].values())
        report_path = tmp_path / "jobs" / "proj-001" / "qa" / "editorial-qa-report.json"
        assert report_path.exists()
        assert ledger_path.exists()
        ledger_entries = [json.loads(line) for line in ledger_path.read_text().splitlines()]
        assert len(ledger_entries) == 1
        assert ledger_entries[0]["script_id"] == "proj-001"

    def test_raises_when_no_script_file(self, pipeline, tmp_path):
        with patch("ytfactory.editorial_qa.pipeline.WORKSPACE_DIR", str(tmp_path)):
            with pytest.raises(FileNotFoundError):
                pipeline.run("proj-missing")

    def test_invalid_checks_never_flagged(self, pipeline, mock_llm, tmp_path):
        checks = self._all_clean_checks()
        checks["sounds_translated"] = {"verdict": "3", "flagged": [], "note": ""}  # claims but uncited
        mock_llm.generate.return_value = _make_response(_qa_report_response(checks))

        with patch("ytfactory.editorial_qa.pipeline.WORKSPACE_DIR", str(tmp_path / "jobs")):
            with patch("ytfactory.editorial_qa.ledger._DEFAULT_LEDGER_PATH", tmp_path / "editorial_qa" / "ledger.jsonl"):
                with patch("ytfactory.editorial_qa.promoter._DEFAULT_STATE_PATH", tmp_path / "editorial_qa" / "promotions.json"):
                    with patch("ytfactory.editorial_qa.promoter._DEFAULT_QA_ROOT", tmp_path / "jobs"):
                        with patch("ytfactory.editorial_qa.promoter.get_llm_provider", return_value=MagicMock()):
                            report = pipeline.run("proj-002", script_text="Some script.")

        assert report["invalid_checks"] == ["sounds_translated"]
        assert report["checks"]["sounds_translated"]["flagged"] is False

    def test_model_emitted_score_is_ignored_entirely(self, pipeline, mock_llm, tmp_path):
        """End-to-end repro of the production bug: even if the model still
        emits a negative editorial_score field (e.g. an old/uncooperative
        model, or a stray field), it must be completely ignored — the report
        and ledger both get the code-derived score instead, never None,
        never the model's number."""
        checks = self._all_clean_checks()
        mock_llm.generate.return_value = _make_response(
            _qa_report_response(checks, editorial_score=-9.2)
        )
        ledger_path = tmp_path / "editorial_qa" / "ledger.jsonl"

        with patch("ytfactory.editorial_qa.pipeline.WORKSPACE_DIR", str(tmp_path / "jobs")):
            with patch("ytfactory.editorial_qa.ledger._DEFAULT_LEDGER_PATH", ledger_path):
                with patch("ytfactory.editorial_qa.promoter._DEFAULT_STATE_PATH", tmp_path / "editorial_qa" / "promotions.json"):
                    with patch("ytfactory.editorial_qa.promoter._DEFAULT_QA_ROOT", tmp_path / "jobs"):
                        with patch("ytfactory.editorial_qa.promoter.get_llm_provider", return_value=MagicMock()):
                            report = pipeline.run("proj-negscore", script_text="Some script.")

        assert report["editorial_score"] == 10.0  # all clean -> derived score, not -9.2, not None
        report_on_disk = json.loads(
            (tmp_path / "jobs" / "proj-negscore" / "qa" / "editorial-qa-report.json").read_text()
        )
        assert report_on_disk["editorial_score"] == 10.0
        ledger_entry = json.loads(ledger_path.read_text().splitlines()[0])
        assert ledger_entry["editorial_score"] == 10.0


# ── Layer 2: Ledger ───────────────────────────────────────────────────────────


class TestQALedger:
    def test_append_and_read_all(self, tmp_path):
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        ledger.append({
            "script_id": "s1", "timestamp": "t1", "editorial_score": 8.0,
            "checks": {"a": {"flagged": True, "invalid": False}},
        })
        ledger.append({
            "script_id": "s2", "timestamp": "t2", "editorial_score": 7.0,
            "checks": {"a": {"flagged": False, "invalid": False}},
        })
        entries = ledger.read_all()
        assert len(entries) == 2
        assert entries[0]["script_id"] == "s1"
        assert entries[1]["script_id"] == "s2"

    def test_append_sanitizes_out_of_range_score(self, tmp_path):
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        ledger.append({
            "script_id": "s-bad", "timestamp": "t1", "editorial_score": -9.2,
            "checks": {"a": {"flagged": False, "invalid": False}},
        })
        entry = ledger.read_all()[0]
        assert entry["editorial_score"] is None

    def test_check_names_discovered(self, tmp_path):
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        ledger.append({"script_id": "s1", "checks": {"a": {"flagged": False, "invalid": False}, "b": {"flagged": True, "invalid": False}}})
        assert ledger.check_names() == ["a", "b"]

    def test_rollup_flag_rate_math(self, tmp_path):
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        for i, flagged in enumerate([True, True, False, True, False]):
            ledger.append({"script_id": f"s{i}", "checks": {"x": {"flagged": flagged, "invalid": False}}})
        rollup = ledger.rollup("x", m=5)
        assert rollup["total"] == 5
        assert rollup["flag_count"] == 3
        assert rollup["flag_rate"] == pytest.approx(0.6)
        assert rollup["scripts"] == ["s0", "s1", "s2", "s3", "s4"]

    def test_rollup_excludes_invalid_from_numerator_and_denominator(self, tmp_path):
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        ledger.append({"script_id": "s0", "checks": {"x": {"flagged": True, "invalid": False}}})
        ledger.append({"script_id": "s1", "checks": {"x": {"flagged": True, "invalid": True}}})  # not evaluated
        ledger.append({"script_id": "s2", "checks": {"x": {"flagged": False, "invalid": False}}})
        rollup = ledger.rollup("x", m=5)
        assert rollup["total"] == 2  # s1 excluded
        assert rollup["flag_count"] == 1
        assert "s1" not in rollup["scripts"]

    def test_rollup_only_looks_back_m_valid_entries(self, tmp_path):
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        for i in range(10):
            ledger.append({"script_id": f"s{i}", "checks": {"x": {"flagged": i < 3, "invalid": False}}})
        rollup = ledger.rollup("x", m=5)
        assert rollup["total"] == 5
        assert rollup["scripts"] == ["s5", "s6", "s7", "s8", "s9"]  # last 5 only
        assert rollup["flag_count"] == 0  # none of the last 5 were flagged

    def test_rollup_empty_ledger(self, tmp_path):
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        rollup = ledger.rollup("x", m=5)
        assert rollup == {"total": 0, "flag_count": 0, "flag_rate": 0.0, "scripts": []}


# ── Layer 3: Pattern Promoter ─────────────────────────────────────────────────


class TestPatternPromoter:
    def _ledger_with_flags(self, tmp_path, flags: list[bool], check_name: str = "sounds_translated") -> QALedger:
        ledger = QALedger(path=tmp_path / "ledger.jsonl")
        for i, flagged in enumerate(flags):
            ledger.append({"script_id": f"s{i}", "checks": {check_name: {"flagged": flagged, "invalid": False}}})
        return ledger

    def _promoter(self, settings, tmp_path, mock_llm):
        with patch("ytfactory.editorial_qa.promoter.get_llm_provider", return_value=mock_llm):
            return PatternPromoter(
                settings,
                state_path=tmp_path / "promotions.json",
                qa_root=tmp_path / "jobs",
            )

    def test_single_flag_never_promotes(self, settings, tmp_path, mock_llm):
        ledger = self._ledger_with_flags(tmp_path, [True, False, False, False, False])
        promoter = self._promoter(settings, tmp_path, mock_llm)
        proposals = promoter.evaluate(ledger)
        assert proposals == []
        mock_llm.generate.assert_not_called()

    def test_n_of_m_triggers_proposal(self, settings, tmp_path, mock_llm):
        ledger = self._ledger_with_flags(tmp_path, [True, True, False, True, True])  # 4 of 5
        mock_llm.generate.return_value = _make_response(
            json.dumps({"summary": "Translation scaffolding recurring.", "proposed_prompt_addition": "Remove residual scaffolding."})
        )
        promoter = self._promoter(settings, tmp_path, mock_llm)
        proposals = promoter.evaluate(ledger)
        assert len(proposals) == 1
        assert proposals[0]["check_name"] == "sounds_translated"
        assert proposals[0]["flag_count"] == 4
        assert proposals[0]["status"] == "pending"
        mock_llm.generate.assert_called_once()

    def test_pending_proposal_not_regenerated(self, settings, tmp_path, mock_llm):
        ledger = self._ledger_with_flags(tmp_path, [True, True, True, True, True])
        mock_llm.generate.return_value = _make_response(
            json.dumps({"summary": "s", "proposed_prompt_addition": "p"})
        )
        promoter = self._promoter(settings, tmp_path, mock_llm)
        first = promoter.evaluate(ledger)
        assert len(first) == 1

        second = promoter.evaluate(ledger)
        assert second == []  # already pending, not regenerated
        assert mock_llm.generate.call_count == 1

    def test_dismiss_starts_cooldown(self, settings, tmp_path, mock_llm):
        ledger = self._ledger_with_flags(tmp_path, [True, True, True, True, True])
        mock_llm.generate.return_value = _make_response(
            json.dumps({"summary": "s", "proposed_prompt_addition": "p"})
        )
        promoter = self._promoter(settings, tmp_path, mock_llm)
        promoter.evaluate(ledger)
        dismissed = promoter.dismiss("sounds_translated")
        assert dismissed is not None

        # Same flag-rate, within cooldown window -> no re-propose.
        proposals = promoter.evaluate(ledger)
        assert proposals == []
        assert mock_llm.generate.call_count == 1  # no second call

    def test_dismiss_cooldown_bypassed_when_flag_rate_rises(self, settings, tmp_path, mock_llm):
        ledger = self._ledger_with_flags(tmp_path, [True, True, True, True, False])  # 4/5 = 0.8
        mock_llm.generate.return_value = _make_response(
            json.dumps({"summary": "s", "proposed_prompt_addition": "p"})
        )
        promoter = self._promoter(settings, tmp_path, mock_llm)
        promoter.evaluate(ledger)
        promoter.dismiss("sounds_translated")

        # Flag-rate rises to 5/5 = 1.0 -> bypasses cooldown even though runs_since < cooldown.
        ledger2 = self._ledger_with_flags(tmp_path, [True, True, True, True, True])
        proposals = promoter.evaluate(ledger2)
        assert len(proposals) == 1
        assert mock_llm.generate.call_count == 2

    def test_cooldown_expires_after_k_runs(self, settings, tmp_path, mock_llm):
        settings.qa_promote_cooldown_runs = 2
        ledger = self._ledger_with_flags(tmp_path, [True, True, True, True, True])
        mock_llm.generate.return_value = _make_response(
            json.dumps({"summary": "s", "proposed_prompt_addition": "p"})
        )
        promoter = self._promoter(settings, tmp_path, mock_llm)
        promoter.evaluate(ledger)  # run 1: proposes
        promoter.dismiss("sounds_translated")
        promoter.evaluate(ledger)  # run 2: within cooldown (1 run since dismissal)
        assert mock_llm.generate.call_count == 1
        proposals = promoter.evaluate(ledger)  # run 3: cooldown (2) has passed
        assert len(proposals) == 1
        assert mock_llm.generate.call_count == 2

    def test_approve_clears_pending_and_never_touches_a_file(self, settings, tmp_path, mock_llm):
        ledger = self._ledger_with_flags(tmp_path, [True, True, True, True, True])
        mock_llm.generate.return_value = _make_response(
            json.dumps({"summary": "s", "proposed_prompt_addition": "p"})
        )
        promoter = self._promoter(settings, tmp_path, mock_llm)
        promoter.evaluate(ledger)

        prompts_dir = Path(__file__).parent.parent / "src" / "ytfactory" / "agents" / "prompts"
        before = {p: p.read_bytes() for p in prompts_dir.glob("*.py")}

        proposal = promoter.approve("sounds_translated")
        assert proposal is not None
        assert promoter.list_pending() == {}

        after = {p: p.read_bytes() for p in prompts_dir.glob("*.py")}
        assert before == after  # not a single prompt file touched

    def test_callback_to_opening_excluded_unless_house_style(self, settings, tmp_path, mock_llm):
        settings.qa_callback_required = False
        ledger = self._ledger_with_flags(tmp_path, [True, True, True, True, True], check_name="callback_to_opening")
        promoter = self._promoter(settings, tmp_path, mock_llm)
        proposals = promoter.evaluate(ledger)
        assert proposals == []
        mock_llm.generate.assert_not_called()

    def test_callback_to_opening_considered_when_house_style_enabled(self, settings, tmp_path, mock_llm):
        settings.qa_callback_required = True
        ledger = self._ledger_with_flags(tmp_path, [True, True, True, True, True], check_name="callback_to_opening")
        mock_llm.generate.return_value = _make_response(
            json.dumps({"summary": "s", "proposed_prompt_addition": "p"})
        )
        promoter = self._promoter(settings, tmp_path, mock_llm)
        proposals = promoter.evaluate(ledger)
        assert len(proposals) == 1


class TestGatherEvidenceExamples:
    def test_pulls_notes_from_flagged_reports_only(self, tmp_path):
        jobs_root = tmp_path / "jobs"
        for sid, flagged, note in [("s1", True, "translated phrasing here"), ("s2", False, "clean")]:
            qa_dir = jobs_root / sid / "qa"
            qa_dir.mkdir(parents=True)
            (qa_dir / "editorial-qa-report.json").write_text(
                json.dumps({"checks": {"sounds_translated": {"flagged": flagged, "note": note}}})
            )
        examples = _gather_evidence_examples(["s1", "s2"], "sounds_translated", jobs_root)
        assert len(examples) == 1
        assert "translated phrasing here" in examples[0]


# ── Eagle script live fixture (post structural pass) ─────────────────────────


class TestEagleScriptFixture:
    def test_eagle_script_end_to_end(self, pipeline, mock_llm, tmp_path):
        script_text = EAGLE_SCRIPT_PATH.read_text(encoding="utf-8")

        checks = {
            "ending_vs_opening": {
                "verdict": "stronger",
                "opening_beat": "A bird once built a nest.",
                "closing_beat": "You have to live fully, stand on your own feet, and build a meaningful life.",
                "note": "The ending escalates to a universal call to action; opening is a quiet observation.",
            },
            "every_story_earns_place": {
                "verdict": "clean",
                "stories": [
                    {"name": "The eagle and the chick", "function": "establishes the core doubt-to-confidence arc", "duplicate_of": None},
                    {"name": "Bhagiratha", "function": "mythic-scale perseverance against impossibility", "duplicate_of": None},
                    {"name": "The watchmaker (Jerome)", "function": "human-scale perseverance against poverty", "duplicate_of": None},
                    {"name": "Vinoba Bhave", "function": "mastery of small things enables greatness", "duplicate_of": None},
                ],
                "note": "Four distinct functions, no duplication found.",
            },
            "unnecessary_explanation": {"verdict": "clean", "violations": [], "note": "No redundant restating found."},
            "callback_to_opening": {
                "verdict": "partial",
                "opening_image": "A bird once built a nest.",
                "ending_quote": "You have to live fully, stand on your own feet, and build a meaningful life.",
                "note": "Ending doesn't literally return to the nest image.",
            },
            "sounds_translated": {"verdict": "clean", "flagged": [], "note": "Reads as originally written English."},
            "open_loop_payoff": {
                "verdict": "paid off",
                "question": "How can I fly like you? I am small.",
                "resolution": "After eight days, it finally soared with absolute confidence.",
                "note": "Resolved mid-script, well before the end.",
            },
        }
        mock_llm.generate.return_value = _make_response(_qa_report_response(checks))

        with patch("ytfactory.editorial_qa.pipeline.WORKSPACE_DIR", str(tmp_path / "jobs")):
            with patch("ytfactory.editorial_qa.ledger._DEFAULT_LEDGER_PATH", tmp_path / "editorial_qa" / "ledger.jsonl"):
                with patch("ytfactory.editorial_qa.promoter._DEFAULT_STATE_PATH", tmp_path / "editorial_qa" / "promotions.json"):
                    with patch("ytfactory.editorial_qa.promoter._DEFAULT_QA_ROOT", tmp_path / "jobs"):
                        with patch("ytfactory.editorial_qa.promoter.get_llm_provider", return_value=MagicMock()):
                            report = pipeline.run("proj-eagle", script_text=script_text)

        assert report["invalid_checks"] == []
        assert report["checks"]["every_story_earns_place"]["flagged"] is False
        assert report["checks"]["callback_to_opening"]["flagged"] is True  # partial != yes, report-only
        # Derived, not model-emitted: one flagged check (callback_to_opening)
        # -> 10.0 - FLAGGED_PENALTY = 8.5.
        assert report["editorial_score"] == 10.0 - FLAGGED_PENALTY
        assert (tmp_path / "jobs" / "proj-eagle" / "qa" / "editorial-qa-report.json").exists()
