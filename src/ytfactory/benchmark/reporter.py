"""Benchmark reporter — Markdown comparison report, visual gallery, and leaderboard."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .models import BenchmarkReport, ModelMetrics, SceneResult

# ── Display helpers ───────────────────────────────────────────────────────────

_DISPLAY_NAMES: dict[str, str] = {
    "minicpm_v2_6": "MiniCPM-V",
    "qwen2_5_vl_3b": "Qwen2.5-VL",
}

_MEDALS = ["🥇", "🥈", "🥉"]

_REC_DISPLAY: dict[str, tuple[str, str]] = {
    "PASS":          ("✅", "APPROVE"),
    "REGENERATE":    ("❌", "REGENERATE"),
    "MANUAL_REVIEW": ("⚠️", "MANUAL REVIEW"),
    "SKIP":          ("⏭️", "SKIP"),
    "ERROR":         ("💥", "ERROR"),
}

_RESULT_DISPLAY: dict[str, str] = {
    "TP": "✅ TRUE POSITIVE",
    "TN": "✅ TRUE NEGATIVE",
    "FP": "❌ FALSE POSITIVE",
    "FN": "❌ FALSE NEGATIVE",
}


class BenchmarkReporter:
    """Writes all benchmark reports to the output directory."""

    def write(self, report: BenchmarkReport, output_dir: Path) -> Path:
        """Write report.md, comparison.md, gallery.md and report-summary.json.

        Returns the path to report.md.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path = output_dir / "report.md"
        json_path = output_dir / "report-summary.json"
        comparison_path = output_dir / "comparison.md"
        gallery_path = output_dir / "gallery.md"

        md_path.write_text(self._build_markdown(report), encoding="utf-8")
        json_path.write_text(
            json.dumps(self._build_summary(report), indent=2, default=str),
            encoding="utf-8",
        )
        comparison_path.write_text(self._build_comparison(report), encoding="utf-8")
        gallery_path.write_text(self._build_gallery(report, output_dir), encoding="utf-8")
        return md_path

    def write_comparison(self, report: BenchmarkReport, output_dir: Path) -> Path:
        """Write comparison.md and return its path."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "comparison.md"
        path.write_text(self._build_comparison(report), encoding="utf-8")
        return path

    def write_gallery(self, report: BenchmarkReport, output_dir: Path) -> Path:
        """Write gallery.md and return its path."""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "gallery.md"
        path.write_text(self._build_gallery(report, output_dir), encoding="utf-8")
        return path

    # ── Per-model summary Markdown ────────────────────────────────────────

    def _build_markdown(self, report: BenchmarkReport) -> str:
        lines: list[str] = []
        _h = lines.append

        _h("# Vision Review Benchmark")
        _h("")
        _h("================================================")
        _h("")
        _h("## Dataset")
        _h("")
        _h(f"- **File:** `{report.dataset_path}`")
        _h(f"- **Total scenes:** {report.total_scenes}")
        _h(f"  - Bad (expected failures): {report.bad_scenes}")
        _h(f"  - Good (expected pass): {report.good_scenes}")
        _h("")
        _h("--------------------------------------------")
        _h("")

        for model in report.models:
            m = report.metrics.get(model)
            results = report.scene_results.get(model, [])
            _h(f"## {_display_name(model)}")
            _h("")
            _h("### Per-scene results")
            _h("")
            _h("| Scene | Expected | Result | Hard Fail | Detected Rules | Score | Latency |")
            _h("|-------|----------|--------|-----------|----------------|-------|---------|")
            for r in results:
                label = _label(r)
                expected = "BAD" if r.expected_failures else "GOOD"
                detected = ", ".join(r.detected_failures) if r.detected_failures else "—"
                fail_mark = "✓" if r.hard_fail else "—"
                _h(
                    f"| {r.scene} | {expected} | {r.recommendation} | {fail_mark} "
                    f"| {detected} | {r.overall_score:.0f} | {r.latency_ms:.0f}ms |"
                )
            _h("")

            if m:
                _h("### Classification metrics")
                _h("")
                _h(f"| Metric | Value |")
                _h(f"|--------|-------|")
                _h(f"| True Positives  | {m.tp} |")
                _h(f"| False Positives | {m.fp} |")
                _h(f"| True Negatives  | {m.tn} |")
                _h(f"| False Negatives | {m.fn} |")
                _h(f"| Precision       | {m.precision:.1%} |")
                _h(f"| Recall          | {m.recall:.1%} |")
                _h(f"| F1 Score        | {m.f1:.1%} |")
                _h(f"| Accuracy        | {m.accuracy:.1%} |")
                _h("")
                _h("### Quality scores (avg across all scenes)")
                _h("")
                _h(f"| Dimension | Score |")
                _h(f"|-----------|-------|")
                _h(f"| Narrative  | {m.avg_narrative:.1f} |")
                _h(f"| Technical  | {m.avg_technical:.1f} |")
                _h(f"| Cinematic  | {m.avg_cinematic:.1f} |")
                _h(f"| Latency    | {m.avg_latency_ms:.0f} ms/scene |")
                _h("")

            _h("--------------------------------------------")
            _h("")

        # ── Hard fail comparison table ─────────────────────────────────
        _h("## Hard Fail Detection Comparison")
        _h("")
        all_scenes = report.scene_results.get(report.models[0], []) if report.models else []
        bad_scene_ids = [r.scene for r in all_scenes if r.expected_failures]

        if bad_scene_ids and len(report.models) > 1:
            header_cols = " | ".join(f"{_display_name(m)}" for m in report.models)
            sep_cols = " | ".join("---" for _ in report.models)
            _h(f"| Scene | Expected Rule | {header_cols} |")
            _h(f"|-------|---------------|-{sep_cols}-|")

            for scene_id in bad_scene_ids:
                first_result = report.scene_results[report.models[0]]
                scene_obj = next((r for r in first_result if r.scene == scene_id), None)
                if not scene_obj:
                    continue
                for rule in scene_obj.expected_failures:
                    cells: list[str] = []
                    for model in report.models:
                        model_result = next(
                            (r for r in report.scene_results.get(model, []) if r.scene == scene_id),
                            None,
                        )
                        if model_result is None:
                            cells.append("N/A")
                        elif rule in model_result.detected_failures:
                            cells.append("✓ detected")
                        else:
                            cells.append("✗ missed")
                    _h(f"| {scene_id} | `{rule}` | {' | '.join(cells)} |")
            _h("")

        # ── Winner ────────────────────────────────────────────────────────
        _h("## Summary")
        _h("")
        if len(report.models) > 1:
            _h("| Model | F1 | Accuracy | Avg Latency |")
            _h("|-------|----|----------|-------------|")
            for model in report.models:
                m = report.metrics.get(model)
                if m:
                    _h(
                        f"| {_display_name(model)} | {m.f1:.1%} | {m.accuracy:.1%} "
                        f"| {m.avg_latency_ms:.0f}ms |"
                    )
            _h("")

        if report.winner:
            _h(f"**Winner: {_display_name(report.winner)}** (highest F1 score)")
        elif len(report.models) > 1:
            _h("**Result: Tied** — models performed equally.")
        _h("")
        _h("================================================")

        return "\n".join(lines) + "\n"

    # ── Visual comparison (text-based, one section per scene) ─────────────

    def _build_comparison(self, report: BenchmarkReport) -> str:
        lines: list[str] = []
        _h = lines.append

        _h("# Vision Review — Visual Comparison Report")
        _h("")
        _h("=" * 50)
        _h("")

        by_scene = _transpose_results(report)
        scene_order = (
            [r.scene for r in report.scene_results.get(report.models[0], [])]
            if report.models
            else []
        )

        for scene_id in scene_order:
            model_results = by_scene.get(scene_id, {})
            if not model_results:
                continue

            first_r = next(iter(model_results.values()))
            expected_bad = bool(first_r.expected_failures)

            _h(f"Scene: {scene_id}")
            _h("")
            _h("Expected Result")
            _h("")
            _h("❌ REGENERATE" if expected_bad else "✅ PASS")
            _h("")

            for model_key in report.models:
                r = model_results.get(model_key)
                if not r:
                    continue
                icon, rec_text = _REC_DISPLAY.get(r.recommendation, ("?", r.recommendation))
                label = _label(r)

                _h("--------------------------------------------")
                _h("")
                _h(_display_name(model_key))
                _h("")
                _h("Recommendation")
                _h("")
                _h(f"{icon} {rec_text}")
                _h("")
                _h("Detected Hard Fails")
                _h("")
                if r.detected_failures:
                    for f in r.detected_failures:
                        _h(f"- {f}")
                else:
                    _h("None")
                _h("")
                _h("Narrative Score")
                _h("")
                _h(f"{r.narrative_score:.0f}")
                _h("")
                _h("Technical Score")
                _h("")
                _h(f"{r.technical_score:.0f}")
                _h("")
                _h("Cinematic Score")
                _h("")
                _h(f"{r.cinematic_score:.0f}")
                _h("")
                _h("Result")
                _h("")
                _h(_RESULT_DISPLAY.get(label, label))
                _h("")

            _h("--------------------------------------------")
            _h("")

            if len(report.models) > 1:
                winner_key, reason = _scene_winner(model_results, report.models)
                _h("Winner")
                _h("")
                _h(f"🏆 {_display_name(winner_key)}" if winner_key else "🤝 Tie")
                _h("")
                _h("Reason")
                _h("")
                _h(reason)
                _h("")

            _h("=" * 50)
            _h("")

        return "\n".join(lines) + "\n"

    # ── Visual gallery (embedded images + leaderboard) ────────────────────

    def _build_gallery(self, report: BenchmarkReport, output_dir: Path) -> str:
        lines: list[str] = []
        _h = lines.append

        _h("# Vision Review Benchmark — Visual Gallery")
        _h("")

        by_scene = _transpose_results(report)
        scene_order = (
            [r.scene for r in report.scene_results.get(report.models[0], [])]
            if report.models
            else []
        )

        for scene_id in scene_order:
            model_results = by_scene.get(scene_id, {})
            if not model_results:
                continue

            first_r = next(iter(model_results.values()))
            expected_bad = bool(first_r.expected_failures)
            img_rel = _image_rel_path(scene_id, report.dataset_path, output_dir)

            _h("---")
            _h("")
            _h(f"## {scene_id.title()}")
            _h("")
            _h(f"![{scene_id}]({img_rel})")
            _h("")
            _h(f"**Expected:** {'❌ REGENERATE' if expected_bad else '✅ PASS'}")
            _h("")

            if len(report.models) > 1:
                _h("| Model | Decision | Result |")
                _h("|-------|----------|--------|")
                for model_key in report.models:
                    r = model_results.get(model_key)
                    if not r:
                        continue
                    icon, rec_text = _REC_DISPLAY.get(r.recommendation, ("?", r.recommendation))
                    label = _label(r)
                    _h(f"| {_display_name(model_key)} | {icon} {rec_text} | {_RESULT_DISPLAY.get(label, label)} |")
                _h("")

                winner_key, reason = _scene_winner(model_results, report.models)
                if winner_key:
                    _h(f"🏆 **Winner: {_display_name(winner_key)}**")
                else:
                    _h("🤝 **Tie**")
                _h("")
                _h(f"> {reason}")
            else:
                model_key = report.models[0]
                r = model_results.get(model_key)
                if r:
                    icon, rec_text = _REC_DISPLAY.get(r.recommendation, ("?", r.recommendation))
                    label = _label(r)
                    _h(
                        f"**{_display_name(model_key)}:** {icon} {rec_text} "
                        f"— {_RESULT_DISPLAY.get(label, label)}"
                    )

            _h("")

        # ── Leaderboard ────────────────────────────────────────────────────
        _h("---")
        _h("")
        _h("## Overall Leaderboard")
        _h("")
        _h("=" * 50)
        _h("")

        ranked = sorted(
            [(m, report.metrics[m]) for m in report.models if m in report.metrics],
            key=lambda x: x[1].benchmark_score,
            reverse=True,
        )

        _h("| Rank | Model | Score |")
        _h("|------|-------|-------|")
        for i, (model_key, m) in enumerate(ranked):
            medal = _MEDALS[i] if i < len(_MEDALS) else f"#{i + 1}"
            _h(f"| {medal} | {_display_name(model_key)} | {m.benchmark_score:.1f} |")
        _h("")

        _h("--------------------------------------------")
        _h("")

        if len(report.models) > 1:
            _h("**True Positives**")
            _h("")
            for model_key, m in ranked:
                _h(f"{_display_name(model_key)}: {m.tp}/{report.bad_scenes}")
            _h("")

            _h("--------------------------------------------")
            _h("")
            _h("**False Positives**")
            _h("")
            for model_key, m in ranked:
                _h(f"{_display_name(model_key)}: {m.fp}")
            _h("")

            _h("--------------------------------------------")
            _h("")
            _h("**False Negatives**")
            _h("")
            for model_key, m in ranked:
                _h(f"{_display_name(model_key)}: {m.fn}")
            _h("")

            _h("--------------------------------------------")
            _h("")
            _h("**Average Technical QA**")
            _h("")
            for model_key, m in ranked:
                _h(f"{_display_name(model_key)}: {m.avg_technical:.1f}")
            _h("")

            _h("--------------------------------------------")
            _h("")
            if report.winner:
                _h(f"**Benchmark Winner: 🏆 {_display_name(report.winner)}**")
                _h("")
                _h(_leaderboard_reason(report.winner, report.models, report.metrics))
            else:
                _h("**Result: 🤝 Tied**")
                _h("")
                _h("All models achieved equivalent classification accuracy.")
        else:
            model_key = ranked[0][0] if ranked else ""
            m = ranked[0][1] if ranked else None
            if m:
                _h(
                    f"F1: {m.f1:.1%} | Accuracy: {m.accuracy:.1%} "
                    f"| Avg Technical: {m.avg_technical:.1f}"
                )

        _h("")
        _h("=" * 50)
        _h("")

        return "\n".join(lines) + "\n"

    # ── JSON summary ──────────────────────────────────────────────────────

    def _build_summary(self, report: BenchmarkReport) -> dict:
        return {
            "dataset": report.dataset_path,
            "total_scenes": report.total_scenes,
            "bad_scenes": report.bad_scenes,
            "good_scenes": report.good_scenes,
            "models": report.models,
            "winner": report.winner,
            "metrics": {
                model: {
                    "tp": m.tp,
                    "fp": m.fp,
                    "tn": m.tn,
                    "fn": m.fn,
                    "precision": round(m.precision, 4),
                    "recall": round(m.recall, 4),
                    "f1": round(m.f1, 4),
                    "accuracy": round(m.accuracy, 4),
                    "benchmark_score": m.benchmark_score,
                    "avg_latency_ms": round(m.avg_latency_ms),
                    "avg_narrative_score": round(m.avg_narrative, 1),
                    "avg_technical_score": round(m.avg_technical, 1),
                    "avg_cinematic_score": round(m.avg_cinematic, 1),
                }
                for model, m in report.metrics.items()
            },
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _display_name(model_key: str) -> str:
    """Convert a registry key to a human-readable display name."""
    return _DISPLAY_NAMES.get(model_key, model_key.replace("_", " ").title())


def _label(r: SceneResult) -> str:
    """Return TP / FP / TN / FN for a single scene result."""
    is_bad = bool(r.expected_failures)
    predicted_fail = r.recommendation == "REGENERATE"
    if is_bad and predicted_fail:
        return "TP"
    if not is_bad and predicted_fail:
        return "FP"
    if not is_bad and not predicted_fail:
        return "TN"
    return "FN"


def _transpose_results(report: BenchmarkReport) -> dict[str, dict[str, SceneResult]]:
    """Pivot {model → [results]} to {scene_id → {model → result}}."""
    by_scene: dict[str, dict[str, SceneResult]] = {}
    for model_key, results in report.scene_results.items():
        for r in results:
            by_scene.setdefault(r.scene, {})[model_key] = r
    return by_scene


def _image_rel_path(scene_id: str, dataset_path: str, output_dir: Path) -> str:
    """Return a path from output_dir to the scene image, suitable for Markdown."""
    image_abs = Path(dataset_path).parent / "images" / f"{scene_id}.png"
    try:
        return os.path.relpath(image_abs, output_dir)
    except ValueError:
        return str(image_abs)


def _scene_winner(
    model_results: dict[str, SceneResult],
    model_order: list[str],
) -> tuple[str | None, str]:
    """Determine which model wins a scene and why.

    Returns (winner_key_or_None, reason_string).
    """
    correct: dict[str, bool] = {}
    for model_key, r in model_results.items():
        expected_bad = bool(r.expected_failures)
        predicted_regen = r.recommendation == "REGENERATE"
        correct[model_key] = (expected_bad and predicted_regen) or (
            not expected_bad and not predicted_regen
        )

    correct_models = [m for m in model_order if correct.get(m, False)]
    wrong_models = [m for m in model_order if not correct.get(m, True)]
    n_models = len([m for m in model_order if m in model_results])

    # All models got it right — compare by QA quality
    if len(correct_models) == n_models and n_models > 0:
        def quality_key(mk: str) -> tuple:
            r = model_results[mk]
            return (r.technical_score, r.narrative_score, r.cinematic_score)

        ranked = sorted(
            [m for m in model_order if m in model_results],
            key=quality_key,
            reverse=True,
        )
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None

        if second and quality_key(best) == quality_key(second):
            return None, "Both models correctly identified the expected result with equal QA scores."

        best_r = model_results[best]
        second_r = model_results[second] if second else None

        if second_r and best_r.technical_score > second_r.technical_score:
            reason = (
                f"Both correctly identified the expected result; "
                f"{_display_name(best)} achieved a higher Technical QA score "
                f"({best_r.technical_score:.0f} vs {second_r.technical_score:.0f})."
            )
        elif second_r and best_r.narrative_score > second_r.narrative_score:
            reason = (
                f"Both correctly identified the expected result; "
                f"{_display_name(best)} achieved a higher Narrative QA score "
                f"({best_r.narrative_score:.0f} vs {second_r.narrative_score:.0f})."
            )
        else:
            reason = (
                f"Both correctly identified the expected result; "
                f"{_display_name(best)} achieved higher overall QA scores."
            )
        return best, reason

    # All models got it wrong
    if not correct_models:
        return None, "Both models produced an incorrect result for this scene."

    # One correct, one wrong
    winner_key = correct_models[0]
    loser_key = wrong_models[0] if wrong_models else None
    winner_r = model_results[winner_key]
    expected_bad = bool(winner_r.expected_failures)
    loser_name = _display_name(loser_key) if loser_key else "the other model"

    if expected_bad:
        detected = (
            ", ".join(winner_r.detected_failures) if winner_r.detected_failures else "the defect"
        )
        reason = (
            f"Correctly detected {detected} while "
            f"{loser_name} incorrectly approved the image."
        )
    else:
        reason = (
            f"Correctly approved the image (no defects) while "
            f"{loser_name} raised a false alarm."
        )

    return winner_key, reason


def _leaderboard_reason(
    winner_key: str,
    models: list[str],
    metrics: dict[str, ModelMetrics],
) -> str:
    """Generate a natural-language explanation of why the winner beat the others."""
    winner_m = metrics[winner_key]
    others = [m for m in models if m != winner_key]

    parts: list[str] = []
    for other_key in others:
        other_m = metrics.get(other_key)
        if not other_m:
            continue
        advantages: list[str] = []
        if winner_m.tp > other_m.tp:
            advantages.append(f"more true positives ({winner_m.tp} vs {other_m.tp})")
        if winner_m.fp < other_m.fp:
            advantages.append(f"fewer false positives ({winner_m.fp} vs {other_m.fp})")
        if winner_m.fn < other_m.fn:
            advantages.append(f"fewer false negatives ({winner_m.fn} vs {other_m.fn})")
        tech_diff = winner_m.avg_technical - other_m.avg_technical
        if abs(tech_diff) >= 1.0:
            direction = "higher" if tech_diff > 0 else "lower"
            advantages.append(
                f"{direction} average Technical QA "
                f"({winner_m.avg_technical:.1f} vs {other_m.avg_technical:.1f})"
            )
        if advantages:
            parts.append(
                f"Outperformed {_display_name(other_key)} with "
                + " and ".join(advantages)
                + "."
            )

    return " ".join(parts) if parts else "Achieved the highest composite benchmark score."
