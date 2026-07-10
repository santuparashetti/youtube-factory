"""CTA Overlay Pipeline — orchestrates placement, rendering, validation, and retry.

Spec: three-step escalation on validation failure:
  1. Retry once with same placement, re-render overlay asset.
  2. If still fails, fall back to ``minimal`` template.
  3. If that also fails, raise CTABlockedError (blocks final mux).
     Failure is reported in cta-review-report.json with a clear reason_code.

When CTA is disabled (config.enabled = False), the pipeline writes a
``cta/cta-timing.json`` stub (enabled=false) so the incremental engine has
a valid output to track, then returns immediately.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from .config import CTAOverlayConfig, load_cta_config
from .models import CTAPlacement, CTAResult, CTAReviewResult, PlacementPath
from .placement import CTAPlacementEngine
from .renderer import CTARenderer
from .reporter import CTAReporter


class CTABlockedError(RuntimeError):
    """Raised when all three escalation steps fail — blocks final mux."""


class CTAPipeline:
    """Run the CTA Overlay stage for a project.

    Usage::

        CTAPipeline().run(project_id)               # reads from Settings()
        CTAPipeline(settings=settings).run(project_id)  # shared Settings instance
    """

    def __init__(self, settings=None) -> None:
        # Defer Settings import to avoid circular deps at module level
        if settings is None:
            from ytfactory.config.settings import Settings
            settings = Settings()
        self._max_retries: int = int(getattr(settings, "cta_max_retries", 3))

    def run(
        self,
        project_id: str,
        config_path: str | None = None,
        *,
        _config: CTAOverlayConfig | None = None,  # injected in tests
    ) -> CTAResult:
        """Apply CTA overlay to video/final.mp4.

        When CTA is disabled, writes a stub and returns immediately.
        Raises CTABlockedError only when three-step escalation is exhausted.
        """
        from ytfactory.shared.constants import WORKSPACE_DIR

        project_dir = Path(WORKSPACE_DIR) / project_id
        config = _config or load_cta_config(config_path)
        reporter = CTAReporter()

        # ── Early exit when disabled ───────────────────────────────────────
        if not config.enabled:
            result = CTAResult(
                success=True,
                enabled=False,
                placement=None,
                review=CTAReviewResult(passed=True),
            )
            reporter.write(project_dir, result)
            logger.info("CTA Overlay: disabled — skipping")
            return result

        final_video = project_dir / "video" / "final.mp4"
        if not final_video.exists():
            raise FileNotFoundError(
                f"CTA stage requires video/final.mp4 — not found in {project_dir}"
            )

        # ── Phase 1: Placement ────────────────────────────────────────────
        placement = CTAPlacementEngine(config).find_placement(project_dir)

        # ── Phase 2: Render + validate (with escalation) ──────────────────
        result = self._render_with_escalation(
            final_video, project_dir, placement, config
        )

        reporter.write(project_dir, result)
        return result

    # ── Escalation logic ──────────────────────────────────────────────────────

    def _render_with_escalation(
        self,
        final_video: Path,
        project_dir: Path,
        placement: CTAPlacement,
        config: CTAOverlayConfig,
    ) -> CTAResult:
        """Three-step escalation per spec."""
        renderer = CTARenderer()
        pre_cta_backup = final_video.with_suffix(".pre-cta.mp4")
        work_output = final_video.with_suffix(".cta-work.mp4")

        # Step 0 — first attempt
        render_result = renderer.render(final_video, work_output, placement, config)
        review = self._validate(render_result, placement, config, final_video)

        if review.passed:
            self._replace_final(final_video, work_output, pre_cta_backup)
            return CTAResult(
                success=True,
                enabled=True,
                placement=placement,
                review=review,
                output_video=str(final_video),
            )

        # Step 1 — retry once with same placement (when max_retries >= 2)
        if self._max_retries >= 2:
            logger.warning("CTA validation failed, retrying once (same placement)")
            work_output.unlink(missing_ok=True)
            render_result = renderer.render(final_video, work_output, placement, config)
            review = self._validate(render_result, placement, config, final_video)
            review.retry_count = 1

            if review.passed:
                self._replace_final(final_video, work_output, pre_cta_backup)
                return CTAResult(
                    success=True,
                    enabled=True,
                    placement=placement,
                    review=review,
                    output_video=str(final_video),
                )

        # Step 2 — fall back to minimal template (when max_retries >= 3)
        if self._max_retries >= 3:
            logger.warning("CTA retry failed, falling back to minimal template")
            work_output.unlink(missing_ok=True)
            minimal_config = self._minimal_config(config)
            render_result = renderer.render(
                final_video, work_output, placement, minimal_config
            )
            review = self._validate(render_result, placement, minimal_config, final_video)
            review.retry_count = 2
            review.fallback_template = "minimal"

            if review.passed:
                self._replace_final(final_video, work_output, pre_cta_backup)
                return CTAResult(
                    success=True,
                    enabled=True,
                    placement=placement,
                    review=review,
                    output_video=str(final_video),
                )

        # Exhausted all configured steps — block final mux
        work_output.unlink(missing_ok=True)
        reason_code = "CTA_RENDER_FAILED_ALL_ATTEMPTS"
        review.reason_code = reason_code
        review.passed = False

        result = CTAResult(
            success=False,
            enabled=True,
            placement=placement,
            review=review,
        )

        CTAReporter().write(project_dir, result)
        raise CTABlockedError(
            f"CTA Overlay Engine: all escalation steps exhausted. "
            f"reason_code={reason_code}. "
            f"Errors: {review.errors}. "
            "Inspect cta/cta-review-report.json for details."
        )

    def _validate(
        self,
        render_result: object,
        placement: CTAPlacement,
        config: CTAOverlayConfig,
        final_video: Path,
    ) -> CTAReviewResult:
        """Internal validation of a render result."""
        from .renderer import CTARenderResult

        assert isinstance(render_result, CTARenderResult)
        errors: list[str] = []
        warnings: list[str] = []

        # Check render success
        if not render_result.success:
            errors.append(f"Render failed: {render_result.error}")
            return CTAReviewResult(
                passed=False,
                errors=errors,
                warnings=warnings,
                timing_valid=True,
                subtitle_safe=placement.subtitle_safe,
                branding_loaded=True,
                animation_completed=False,
            )

        # Check output file exists and is non-empty
        out = Path(render_result.output_path)
        if not out.exists() or out.stat().st_size < 10_000:
            errors.append("CTA render output missing or suspiciously small")
            return CTAReviewResult(
                passed=False,
                errors=errors,
                warnings=warnings,
                animation_completed=False,
            )

        # Branding check: config loaded without defaults-only fallback
        branding_loaded = bool(config.accent_color and config.accent_color != "")
        if not branding_loaded:
            warnings.append("Branding accent_color not set — using default")

        # Timing validity
        video_dur = _probe_dur(final_video)
        timing_valid = 0 < placement.timestamp < video_dur
        if not timing_valid:
            errors.append(
                f"CTA timestamp {placement.timestamp:.1f}s out of bounds "
                f"(video_duration={video_dur:.1f}s)"
            )

        # Subtitle safety (informational in fallback mode)
        if (
            not placement.subtitle_safe
            and placement.placement_path == PlacementPath.PRIMARY_CONTEXTUAL
        ):
            warnings.append(
                "CTA placed in fallback mode with possible subtitle overlap"
            )

        # BGM secondary duck (informational — duck is applied via FFmpeg filter)
        bgm_duck_applied = config.bgm_secondary_duck_db > 0

        passed = len(errors) == 0
        return CTAReviewResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            timing_valid=timing_valid,
            subtitle_safe=placement.subtitle_safe,
            branding_loaded=branding_loaded,
            animation_completed=True,
            bgm_duck_applied=bgm_duck_applied,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _replace_final(
        self,
        final_video: Path,
        work_output: Path,
        backup: Path,
    ) -> None:
        """Swap work output → final.mp4 (keep pre-cta backup)."""
        if final_video.exists():
            final_video.rename(backup)
        work_output.rename(final_video)

    def _minimal_config(self, base: CTAOverlayConfig) -> CTAOverlayConfig:
        """Return a copy of config with minimal template (lowest asset complexity)."""
        import dataclasses

        minimal = dataclasses.replace(
            base,
            template="minimal",
            panel_alpha=0.0,
            border_alpha=0.0,
            show_like=False,
            show_bell=False,
        )
        return minimal


def _probe_dur(path: Path) -> float:
    import json
    import subprocess

    try:
        r = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0
