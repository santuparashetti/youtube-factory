"""Tests for the Auto Remediation Engine V1.

Covers:
  - RemediationConfig (defaults, overrides)
  - RemediationAction, RemediationPlan, RemediationCycle, RetryHistoryEntry,
    RegeneratedAsset, RemediationReport (model fields, to_dict, serialization)
  - DecisionEngine (plan, dedup, severity sort, cost, EFL/RCA phase, retry counts)
  - DryRunExecutor (records calls, returns synthetic results)
  - RemediationReporter (writes 4 files, content checks)
  - AutoRemediationEngine (no_actions, dry_run, VQRE integration mock)
  - Backward compatibility: existing review pipeline unaffected
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytfactory.review.remediation.config import (
    CATEGORY_STRATEGY_MAP,
    ENGINE_STRATEGY_MAP,
    STRATEGIES,
    STRATEGY_COST,
    RemediationConfig,
)
from ytfactory.review.remediation.decision import (
    DecisionEngine,
    _build_retry_counts,
    _select_strategy,
    _severity_rank,
)
from ytfactory.review.remediation.engine import (
    AutoRemediationEngine,
    _extract_verdict,
    _load_scenes,
)
from ytfactory.review.remediation.executor import DryRunExecutor, RemediationExecutorBase
from ytfactory.review.remediation.models import (
    ACTION_STATUSES,
    STOPPED_REASONS,
    RegeneratedAsset,
    RemediationAction,
    RemediationCycle,
    RemediationPlan,
    RemediationReport,
    RetryHistoryEntry,
)
from ytfactory.review.remediation.reporter import (
    RemediationReporter,
    regenerated_assets_path,
    remediation_directory,
    remediation_plan_path,
    remediation_report_md_path,
    retry_history_path,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_action(
    action_id: str = "ARE-0001",
    strategy: str = "retry_validation",
    engine_target: str = "TTS Engine",
    category: str = "audio",
    severity: str = "high",
    confidence: int = 80,
    scene_index: int | None = None,
) -> RemediationAction:
    return RemediationAction(
        action_id=action_id,
        strategy=strategy,
        engine_target=engine_target,
        category=category,
        severity=severity,
        confidence=confidence,
        rationale="test rationale",
        estimated_cost=STRATEGY_COST.get(strategy, 0.0),
        scene_index=scene_index,
    )


def _make_plan(actions: list[RemediationAction] | None = None) -> RemediationPlan:
    return RemediationPlan(
        project_id="test-project",
        timestamp=_ts(),
        actions=actions or [],
        quality_score_before=45.0,
        quality_threshold=70.0,
        max_retries=3,
        estimated_total_cost=0.5,
        decision_summary="1 action planned",
    )


def _make_report(
    plan: RemediationPlan | None = None,
    dry_run: bool = False,
    stopped_reason: str = "no_actions_needed",
) -> RemediationReport:
    return RemediationReport(
        project_id="test-project",
        timestamp=_ts(),
        plan=plan or _make_plan(),
        final_verdict="FAIL",
        final_quality_score=45.0,
        stopped_reason=stopped_reason,
        dry_run=dry_run,
    )


# ── TestRemediationConfig ─────────────────────────────────────────────────────


class TestRemediationConfig:
    def test_defaults(self) -> None:
        cfg = RemediationConfig()
        assert cfg.quality_threshold == 70.0
        assert cfg.min_confidence == 60
        assert cfg.max_retries == 3
        assert cfg.max_cost_estimate == 20.0
        assert cfg.remediate_severities == ["critical", "high"]
        assert cfg.dry_run is False
        assert cfg.require_approval is False
        assert cfg.enable_rollback is True
        assert cfg.allow_full_regeneration is False

    def test_overrides(self) -> None:
        cfg = RemediationConfig(quality_threshold=85.0, dry_run=True, max_retries=1)
        assert cfg.quality_threshold == 85.0
        assert cfg.dry_run is True
        assert cfg.max_retries == 1

    def test_strategies_list_not_empty(self) -> None:
        assert len(STRATEGIES) >= 5

    def test_all_engines_have_strategy(self) -> None:
        for engine in ENGINE_STRATEGY_MAP:
            assert ENGINE_STRATEGY_MAP[engine] in STRATEGIES

    def test_all_categories_have_strategy(self) -> None:
        for category in CATEGORY_STRATEGY_MAP:
            assert CATEGORY_STRATEGY_MAP[category] in STRATEGIES

    def test_strategy_costs_non_negative(self) -> None:
        for strategy, cost in STRATEGY_COST.items():
            assert cost >= 0.0


# ── TestRemediationAction ─────────────────────────────────────────────────────


class TestRemediationAction:
    def test_fields(self) -> None:
        action = _make_action()
        assert action.action_id == "ARE-0001"
        assert action.status == "pending"
        assert action.attempt_count == 0
        assert action.outcome == ""

    def test_to_dict_keys(self) -> None:
        action = _make_action()
        d = action.to_dict()
        assert "action_id" in d
        assert "strategy" in d
        assert "engine_target" in d
        assert "category" in d
        assert "severity" in d
        assert "confidence" in d
        assert "rationale" in d
        assert "estimated_cost" in d
        assert "scene_index" in d
        assert "rule_id" in d
        assert "status" in d

    def test_to_dict_values(self) -> None:
        action = _make_action(scene_index=2)
        d = action.to_dict()
        assert d["scene_index"] == 2
        assert d["status"] == "pending"

    def test_action_statuses_constant(self) -> None:
        assert "pending" in ACTION_STATUSES
        assert "completed" in ACTION_STATUSES
        assert "failed" in ACTION_STATUSES


# ── TestRemediationPlan ───────────────────────────────────────────────────────


class TestRemediationPlan:
    def test_total_actions_property(self) -> None:
        plan = _make_plan(actions=[_make_action(), _make_action("ARE-0002")])
        assert plan.total_actions == 2

    def test_to_dict_has_version(self) -> None:
        plan = _make_plan()
        d = plan.to_dict()
        assert d["version"] == "v1"
        assert "actions" in d
        assert isinstance(d["actions"], list)

    def test_to_dict_json_serializable(self) -> None:
        plan = _make_plan(actions=[_make_action()])
        json.dumps(plan.to_dict())  # must not raise


# ── TestRemediationCycle ──────────────────────────────────────────────────────


class TestRemediationCycle:
    def test_to_dict(self) -> None:
        cycle = RemediationCycle(
            cycle_number=1,
            timestamp=_ts(),
            actions_attempted=2,
            actions_succeeded=1,
            actions_failed=1,
            quality_score_before=40.0,
            quality_score_after=55.0,
            verdict_before="FAIL",
            verdict_after="FAIL",
            elapsed_seconds=1.234,
        )
        d = cycle.to_dict()
        assert d["cycle_number"] == 1
        assert d["actions_attempted"] == 2
        assert d["threshold_met"] is False


# ── TestRetryHistoryEntry ─────────────────────────────────────────────────────


class TestRetryHistoryEntry:
    def test_to_dict(self) -> None:
        entry = RetryHistoryEntry(
            cycle=1,
            action_id="ARE-0001",
            strategy="regenerate_audio",
            engine_target="TTS Engine",
            category="audio",
            scene_index=None,
            timestamp=_ts(),
            success=True,
            outcome="Regenerated 1 audio file",
            elapsed_seconds=2.5,
        )
        d = entry.to_dict()
        assert d["success"] is True
        assert d["strategy"] == "regenerate_audio"


# ── TestRegeneratedAsset ──────────────────────────────────────────────────────


class TestRegeneratedAsset:
    def test_to_dict(self) -> None:
        asset = RegeneratedAsset(
            cycle=1,
            strategy="regenerate_image",
            category="image",
            scene_index=0,
            file_path="/workspace/jobs/p1/images/scene-001.png",
            backed_up_to="/workspace/jobs/p1/remediation/backups/cycle-01/scene-001.png",
        )
        d = asset.to_dict()
        assert d["cycle"] == 1
        assert d["scene_index"] == 0
        assert "backed_up_to" in d


# ── TestRemediationReport ─────────────────────────────────────────────────────


class TestRemediationReport:
    def test_to_dict_has_version(self) -> None:
        report = _make_report()
        d = report.to_dict()
        assert d["version"] == "v1"

    def test_to_dict_json_serializable(self) -> None:
        report = _make_report()
        json.dumps(report.to_dict())  # must not raise

    def test_stopped_reasons_constant(self) -> None:
        assert "no_actions_needed" in STOPPED_REASONS
        assert "dry_run" in STOPPED_REASONS
        assert "quality_threshold_met" in STOPPED_REASONS
        assert "max_retries_reached" in STOPPED_REASONS


# ── TestDecisionEngine ────────────────────────────────────────────────────────


class TestDecisionEngine:
    def _cfg(self, **kw) -> RemediationConfig:
        return RemediationConfig(**kw)

    def test_empty_plan_when_no_reports(self) -> None:
        engine = DecisionEngine(self._cfg())
        plan = engine.plan("proj", None, None, None, None)
        assert plan.actions == []
        assert plan.decision_summary != ""

    def test_plan_empty_when_score_meets_threshold(self) -> None:
        score_report = MagicMock()
        score_report.overall_score = 80.0
        engine = DecisionEngine(self._cfg(quality_threshold=70.0))
        plan = engine.plan("proj", None, None, score_report, None)
        assert plan.actions == []
        assert "already meets" in plan.decision_summary

    def test_select_strategy_engine_takes_priority(self) -> None:
        result = _select_strategy("TTS Engine", "script")
        assert result == "regenerate_audio"  # TTS Engine → regenerate_audio (not retry_validation)

    def test_select_strategy_fallback_to_category(self) -> None:
        result = _select_strategy("Unknown Engine", "audio")
        assert result == "regenerate_audio"

    def test_select_strategy_default_retry(self) -> None:
        result = _select_strategy("Unknown Engine", "unknown_category")
        assert result == "retry_validation"

    def test_severity_rank(self) -> None:
        assert _severity_rank("critical") < _severity_rank("high")
        assert _severity_rank("high") < _severity_rank("medium")
        assert _severity_rank("medium") < _severity_rank("low")

    def test_build_retry_counts_empty(self) -> None:
        counts = _build_retry_counts([])
        assert counts == {}

    def test_build_retry_counts_accumulates(self) -> None:
        history = [
            {"engine_target": "TTS Engine", "rule_id": "R001"},
            {"engine_target": "TTS Engine", "rule_id": "R001"},
            {"engine_target": "Image Generation Engine", "rule_id": "R002"},
        ]
        counts = _build_retry_counts(history)
        assert counts[("TTS Engine", "R001")] == 2
        assert counts[("Image Generation Engine", "R002")] == 1

    def test_plan_actions_sorted_by_severity(self) -> None:
        # Create EFL feedback with mixed severities
        efl_report = MagicMock()
        items = []
        for sev in ("low", "critical", "high"):
            item = MagicMock()
            item.priority = sev
            item.confidence = 80
            item.engine_owner = "TTS Engine"
            item.category = "audio"
            item.rule_id = f"R-{sev}"
            item.feedback_id = f"EFL-{sev}"
            item.root_cause = "test"
            item.recommended_fix = "fix"
            item.severity = sev
            items.append(item)
        efl_report.feedback_items = items

        cfg = RemediationConfig(remediate_severities=["critical", "high", "low"])
        engine = DecisionEngine(cfg)
        plan = engine.plan("proj", None, None, None, efl_report)

        severities = [a.severity for a in plan.actions]
        assert severities == sorted(severities, key=_severity_rank)

    def test_plan_deduplicates_same_strategy_category_scene(self) -> None:
        efl_report = MagicMock()
        items = []
        for i in range(3):
            item = MagicMock()
            item.priority = "high"
            item.confidence = 75
            item.engine_owner = "TTS Engine"
            item.category = "audio"
            item.rule_id = f"R-{i}"
            item.feedback_id = f"EFL-{i}"
            item.root_cause = "audio issue"
            item.recommended_fix = "regenerate"
            item.severity = "high"
            items.append(item)
        efl_report.feedback_items = items

        engine = DecisionEngine(RemediationConfig())
        plan = engine.plan("proj", None, None, None, efl_report)
        # All 3 items → same (strategy, category, scene_index) → only 1 action
        assert len(plan.actions) == 1

    def test_plan_filters_by_confidence(self) -> None:
        efl_report = MagicMock()
        item = MagicMock()
        item.priority = "critical"
        item.confidence = 40  # below default min_confidence=60
        item.engine_owner = "TTS Engine"
        item.category = "audio"
        item.rule_id = "R001"
        item.feedback_id = "EFL-001"
        item.root_cause = "test"
        item.recommended_fix = "fix"
        item.severity = "critical"
        efl_report.feedback_items = [item]

        engine = DecisionEngine(RemediationConfig(min_confidence=60))
        plan = engine.plan("proj", None, None, None, efl_report)
        assert plan.actions == []

    def test_plan_assigns_sequential_ids(self) -> None:
        efl_report = MagicMock()
        items = []
        for i in range(3):
            item = MagicMock()
            item.priority = "high"
            item.confidence = 80
            item.engine_owner = "TTS Engine" if i == 0 else "Image Generation Engine"
            item.category = "audio" if i == 0 else "image"
            item.rule_id = f"R-{i}"
            item.feedback_id = f"EFL-{i}"
            item.root_cause = "test"
            item.recommended_fix = "fix"
            item.severity = "high"
            items.append(item)
        efl_report.feedback_items = items

        engine = DecisionEngine(RemediationConfig())
        plan = engine.plan("proj", None, None, None, efl_report)
        for i, action in enumerate(plan.actions, start=1):
            assert action.action_id == f"ARE-{i:04d}"

    def test_plan_blocks_full_regen_by_default(self) -> None:
        efl_report = MagicMock()
        item = MagicMock()
        item.priority = "critical"
        item.confidence = 90
        item.engine_owner = "Unknown Engine"  # → no engine map entry
        item.category = "story"  # → retry_validation, not full_regeneration
        item.rule_id = "R001"
        item.feedback_id = "EFL-001"
        item.root_cause = "test"
        item.recommended_fix = "fix"
        item.severity = "critical"
        efl_report.feedback_items = [item]

        engine = DecisionEngine(RemediationConfig(allow_full_regeneration=False))
        plan = engine.plan("proj", None, None, None, efl_report)
        for action in plan.actions:
            assert action.strategy != "full_regeneration"

    def test_plan_fills_gaps_from_rca(self) -> None:
        # No EFL items, one RCA issue
        rca_report = MagicMock()
        issue = MagicMock()
        issue.severity = "critical"
        issue.confidence = 80
        issue.primary_engine = "Image Generation Engine"
        issue.category = "image"
        issue.rule_id = "R001"
        issue.issue_id = "RCA-001"
        issue.root_cause_description = "image corrupt"
        issue.suggested_fix = "regenerate"
        issue.scene_index = None
        rca_report.issues = [issue]

        engine = DecisionEngine(RemediationConfig())
        plan = engine.plan("proj", None, rca_report, None, None)
        assert len(plan.actions) == 1
        assert plan.actions[0].strategy == "regenerate_image"
        assert plan.actions[0].source_issue == "RCA-001"


# ── TestDryRunExecutor ────────────────────────────────────────────────────────


class TestDryRunExecutor:
    def test_execute_records_call(self) -> None:
        executor = DryRunExecutor()
        action = _make_action()
        ok, outcome, assets = executor.execute(
            action=action,
            project_dir=Path("/tmp/fake"),
            scenes=[],
            cycle=1,
        )
        assert ok is True
        assert "[dry-run]" in outcome
        assert assets == []
        assert len(executor.calls) == 1
        assert executor.calls[0]["action_id"] == "ARE-0001"

    def test_execute_multiple_calls(self) -> None:
        executor = DryRunExecutor()
        for i in range(3):
            action = _make_action(action_id=f"ARE-{i+1:04d}")
            executor.execute(action=action, project_dir=Path("/tmp"), scenes=[], cycle=1)
        assert len(executor.calls) == 3

    def test_is_base_subclass(self) -> None:
        assert issubclass(DryRunExecutor, RemediationExecutorBase)


# ── TestRemediationReporter ───────────────────────────────────────────────────


class TestRemediationReporter:
    @pytest.fixture
    def tmp_ws(self, tmp_path: Path, monkeypatch) -> Path:
        monkeypatch.setattr(
            "ytfactory.review.remediation.reporter.WORKSPACE_DIR", str(tmp_path)
        )
        return tmp_path

    def test_remediation_directory_created(self, tmp_ws: Path) -> None:
        remediation_directory("p1")
        assert (tmp_ws / "p1" / "remediation").is_dir()

    def test_path_helpers(self, tmp_ws: Path) -> None:
        assert remediation_plan_path("p1").name == "remediation-plan.json"
        assert remediation_report_md_path("p1").name == "remediation-report.md"
        assert retry_history_path("p1").name == "retry-history.json"
        assert regenerated_assets_path("p1").name == "regenerated-assets.json"

    def test_write_creates_four_files(self, tmp_ws: Path) -> None:
        report = _make_report()
        RemediationReporter().write(report)
        base = tmp_ws / "test-project" / "remediation"
        assert (base / "remediation-plan.json").exists()
        assert (base / "remediation-report.md").exists()
        assert (base / "retry-history.json").exists()
        assert (base / "regenerated-assets.json").exists()

    def test_plan_json_is_valid_json(self, tmp_ws: Path) -> None:
        report = _make_report(plan=_make_plan(actions=[_make_action()]))
        RemediationReporter().write(report)
        data = json.loads(
            (tmp_ws / "test-project" / "remediation" / "remediation-plan.json").read_text()
        )
        assert data["version"] == "v1"
        assert isinstance(data["actions"], list)

    def test_retry_history_json_valid(self, tmp_ws: Path) -> None:
        report = _make_report()
        report.retry_history = [
            RetryHistoryEntry(
                cycle=1,
                action_id="ARE-0001",
                strategy="regenerate_audio",
                engine_target="TTS Engine",
                category="audio",
                scene_index=None,
                timestamp=_ts(),
                success=True,
                outcome="done",
                elapsed_seconds=0.5,
            )
        ]
        RemediationReporter().write(report)
        data = json.loads(
            (tmp_ws / "test-project" / "remediation" / "retry-history.json").read_text()
        )
        assert data["total_entries"] == 1
        assert data["entries"][0]["strategy"] == "regenerate_audio"

    def test_regenerated_assets_json_valid(self, tmp_ws: Path) -> None:
        report = _make_report()
        report.regenerated_assets = [
            RegeneratedAsset(
                cycle=1,
                strategy="regenerate_image",
                category="image",
                scene_index=0,
                file_path="/workspace/images/scene-001.png",
            )
        ]
        RemediationReporter().write(report)
        data = json.loads(
            (tmp_ws / "test-project" / "remediation" / "regenerated-assets.json").read_text()
        )
        assert data["total_assets"] == 1

    def test_report_md_contains_verdict(self, tmp_ws: Path) -> None:
        report = _make_report()
        RemediationReporter().write(report)
        md = (tmp_ws / "test-project" / "remediation" / "remediation-report.md").read_text()
        assert "FAIL" in md or "PASS" in md
        assert "Auto Remediation Engine" in md

    def test_report_md_dry_run_tag(self, tmp_ws: Path) -> None:
        report = _make_report(dry_run=True, stopped_reason="dry_run")
        RemediationReporter().write(report)
        md = (tmp_ws / "test-project" / "remediation" / "remediation-report.md").read_text()
        assert "DRY RUN" in md

    def test_report_md_has_planned_actions_table(self, tmp_ws: Path) -> None:
        plan = _make_plan(actions=[_make_action("ARE-0001", "regenerate_audio", "TTS Engine", "audio")])
        report = _make_report(plan=plan)
        RemediationReporter().write(report)
        md = (tmp_ws / "test-project" / "remediation" / "remediation-report.md").read_text()
        assert "ARE-0001" in md
        assert "regenerate_audio" in md

    def test_report_md_with_cycles(self, tmp_ws: Path) -> None:
        report = _make_report()
        report.cycles = [
            RemediationCycle(
                cycle_number=1,
                timestamp=_ts(),
                actions_attempted=1,
                actions_succeeded=1,
                actions_failed=0,
                quality_score_before=40.0,
                quality_score_after=65.0,
                verdict_before="FAIL",
                verdict_after="FAIL",
                elapsed_seconds=2.0,
            )
        ]
        RemediationReporter().write(report)
        md = (tmp_ws / "test-project" / "remediation" / "remediation-report.md").read_text()
        assert "Cycle 1" in md
        assert "40.0" in md
        assert "65.0" in md


# ── TestAutoRemediationEngine ─────────────────────────────────────────────────


class TestAutoRemediationEngine:
    @pytest.fixture
    def tmp_ws(self, tmp_path: Path, monkeypatch) -> Path:
        monkeypatch.setattr(
            "ytfactory.review.remediation.reporter.WORKSPACE_DIR", str(tmp_path)
        )
        monkeypatch.setattr(
            "ytfactory.review.remediation.engine.WORKSPACE_DIR", str(tmp_path)
        )
        return tmp_path

    def _mock_review_report(self, score: float = 45.0, verdict: str = "FAIL") -> MagicMock:
        """Return a mock ReviewReport that looks like the real object."""
        report = MagicMock()
        report.verdict = verdict

        score_obj = MagicMock()
        score_obj.overall_score = score
        report.quality_score_report = score_obj

        report.validation_report = None
        report.rca_report = None
        report.efl_report = None
        return report

    def test_engine_constructs_with_dry_run(self) -> None:
        engine = AutoRemediationEngine(config=RemediationConfig(dry_run=True))
        assert isinstance(engine._executor, DryRunExecutor)

    def test_engine_no_actions_returns_early(self, tmp_ws: Path) -> None:
        review_report = self._mock_review_report(score=90.0, verdict="PASS")
        engine = AutoRemediationEngine(config=RemediationConfig(dry_run=True))
        report = engine.remediate("test-project", review_report)
        assert report.stopped_reason in ("no_actions_needed", "dry_run")
        assert report.plan.actions == []

    def test_engine_dry_run_does_not_execute(self, tmp_ws: Path) -> None:
        # Score below threshold → plan has actions → but dry_run stops before execution
        review_report = self._mock_review_report(score=40.0)

        efl_report = MagicMock()
        item = MagicMock()
        item.priority = "critical"
        item.confidence = 85
        item.engine_owner = "TTS Engine"
        item.category = "audio"
        item.rule_id = "R001"
        item.feedback_id = "EFL-001"
        item.root_cause = "audio broken"
        item.recommended_fix = "regenerate"
        item.severity = "critical"
        efl_report.feedback_items = [item]
        review_report.efl_report = efl_report

        # Use a real DryRunExecutor to verify no actual executor calls happen
        dry_executor = DryRunExecutor()
        engine = AutoRemediationEngine(
            config=RemediationConfig(dry_run=True),
            executor=dry_executor,
        )
        report = engine.remediate("test-project", review_report)
        assert report.stopped_reason == "dry_run"
        assert dry_executor.calls == []  # executor never touched

    def test_engine_writes_output_files(self, tmp_ws: Path) -> None:
        review_report = self._mock_review_report(score=90.0, verdict="PASS")
        engine = AutoRemediationEngine(config=RemediationConfig(dry_run=True))
        engine.remediate("test-project", review_report)
        base = tmp_ws / "test-project" / "remediation"
        assert (base / "remediation-plan.json").exists()
        assert (base / "remediation-report.md").exists()
        assert (base / "retry-history.json").exists()
        assert (base / "regenerated-assets.json").exists()

    def test_extract_verdict_from_dataclass(self) -> None:
        obj = MagicMock()
        obj.verdict = "PASS"
        assert _extract_verdict(obj) == "PASS"

    def test_extract_verdict_from_dict(self) -> None:
        assert _extract_verdict({"verdict": "FAIL"}) == "FAIL"

    def test_extract_verdict_unknown(self) -> None:
        assert _extract_verdict(object()) == "UNKNOWN"

    def test_load_scenes_empty_when_no_file(self, tmp_ws: Path) -> None:
        scenes = _load_scenes(tmp_ws / "no-such-project")
        assert scenes == []

    def test_load_scenes_returns_list(self, tmp_ws: Path) -> None:
        project_dir = tmp_ws / "test-project"
        (project_dir / "scenes").mkdir(parents=True)
        (project_dir / "scenes" / "scene-plan.json").write_text(
            json.dumps({"scenes": [{"narration": "Hello"}, {"narration": "World"}]}),
            encoding="utf-8",
        )
        scenes = _load_scenes(project_dir)
        assert len(scenes) == 2

    def test_engine_with_efl_actions_and_mock_executor(self, tmp_ws: Path) -> None:
        """Full dry-run integration: EFL items → plan → DryRunExecutor."""
        review_report = self._mock_review_report(score=40.0)

        efl_report = MagicMock()
        item = MagicMock()
        item.priority = "high"
        item.confidence = 75
        item.engine_owner = "Image Generation Engine"
        item.category = "image"
        item.rule_id = "R-IMG-001"
        item.feedback_id = "EFL-001"
        item.root_cause = "blurry image"
        item.recommended_fix = "regenerate with higher guidance"
        item.severity = "high"
        efl_report.feedback_items = [item]
        review_report.efl_report = efl_report

        engine = AutoRemediationEngine(config=RemediationConfig(dry_run=True))
        report = engine.remediate("test-project", review_report)

        # Dry-run: plan populated, no execution, file written
        assert report.stopped_reason == "dry_run"
        assert report.plan.total_actions == 1
        assert report.plan.actions[0].strategy == "regenerate_image"
        assert (tmp_ws / "test-project" / "remediation" / "remediation-plan.json").exists()


# ── Backward compatibility: existing review pipeline unaffected ───────────────


class TestBackwardCompatibility:
    """Ensure ARE is additive — existing VQRE/models unaffected."""

    def test_review_models_unmodified(self) -> None:
        from ytfactory.review.models import ReviewReport as RR
        import dataclasses
        fields = {f.name for f in dataclasses.fields(RR)}
        # Core fields still present
        assert "project_id" in fields
        assert "verdict" in fields
        assert "scene_reviews" in fields
        assert "stage_results" in fields

    def test_remediation_module_importable(self) -> None:
        from ytfactory.review.remediation import __init__  # noqa: F401

    def test_config_importable(self) -> None:
        from ytfactory.review.remediation.config import RemediationConfig  # noqa: F401

    def test_models_importable(self) -> None:
        from ytfactory.review.remediation.models import RemediationReport  # noqa: F401

    def test_decision_importable(self) -> None:
        from ytfactory.review.remediation.decision import DecisionEngine  # noqa: F401

    def test_executor_importable(self) -> None:
        from ytfactory.review.remediation.executor import DryRunExecutor  # noqa: F401

    def test_engine_importable(self) -> None:
        from ytfactory.review.remediation.engine import AutoRemediationEngine  # noqa: F401

    def test_reporter_importable(self) -> None:
        from ytfactory.review.remediation.reporter import RemediationReporter  # noqa: F401

    def test_cli_importable(self) -> None:
        from ytfactory.review.remediation.cli import remediate  # noqa: F401

    def test_artifacts_has_remediation_directory(self) -> None:
        from ytfactory.review.artifacts import remediation_directory  # noqa: F401
        assert callable(remediation_directory)
