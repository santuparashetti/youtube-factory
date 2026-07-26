"""Regression guards: the brand_card asset must always be resolved from
assets/branding/ (or wherever the brand config points) at read time — never
copied into a job's workspace/jobs/<id>/images/ folder during Phase 1, and
scene-plan.json must never store a job-local path for it.

Investigation (2026-07-26) found the current code already satisfies both
invariants — scene_assets.py reassigns image_path to asset_path without
copying bytes, and _mark_asset_scenes() writes the brand config's asset_path
verbatim. These tests lock that behavior in so a future change can't
reintroduce the caching bug that motivated earlier fixes (see git history:
f5845d2, cb74cc4, 66d2ae7).
"""

from __future__ import annotations

from unittest.mock import patch

from ytfactory.config.settings import Settings


class TestBrandCardNotCopiedIntoJobFolder:
    """Phase 1 (generate_scene_assets) must not write the brand asset's
    bytes into the job's images/ folder — only resolve the path."""

    def test_brand_card_not_copied_into_job_images_folder(self, tmp_path, monkeypatch):
        from ytfactory.agents.nodes.scene_assets import generate_scene_assets

        jobs_root = tmp_path / "jobs"
        monkeypatch.setattr(
            "ytfactory.agents.nodes.scene_assets.WORKSPACE_DIR", str(jobs_root)
        )

        scene = {
            "index": 30,
            "title": "Brand Card",
            "narration": "This is Atma Theory.",
            "visual_prompt": "Cinematic wide shot, Brand Card, golden hour lighting.",
            "duration_seconds": 10,
            "scene_type": "brand_card",
            "asset_id": "assets/branding/atma-theory-brand.png",
            "asset_path": "assets/branding/atma-theory-brand.png",
        }
        state: dict = {
            "current_scene": scene,
            "project_id": "brandtest",
            "language": "en",
            "style": "spiritual",
            "skip_images": False,
            "scene_plan": [scene],
        }

        settings = Settings(voice_enabled=False)

        with patch(
            "ytfactory.agents.nodes.scene_assets.Settings", return_value=settings
        ):
            result = generate_scene_assets(state)

        images_dir = jobs_root / "brandtest" / "images"
        job_local_copy = images_dir / "scene-030.png"
        assert not job_local_copy.exists(), (
            "Brand card must not be copied into the job's images/ folder"
        )

        # The resolved path handed back to the graph must point at the
        # source asset, not a job-local file.
        resolved = result.get("image_paths", {}).get(30, "")
        assert "assets/branding" in resolved.replace("\\", "/"), resolved
        assert str(images_dir) not in resolved, resolved


class TestBrandCardScenePlanAssetPath:
    """_mark_asset_scenes() must always write the brand config's asset_path
    verbatim — never a job-local (workspace/jobs/...) path.

    Uses an isolated brand_config.yaml fixture rather than the live
    config/brand_config.yaml — that file's closing/cta/signature `enabled`
    flags are operationally toggled outside of git (uncommitted local
    edits), so asserting against it directly would make this test flaky.
    """

    def test_brand_card_asset_path_points_at_source_not_job_folder(self, tmp_path):
        import yaml

        from ytfactory.agents.nodes.scene_planner import _mark_asset_scenes
        from ytfactory.branding.config import get_brand_config, reset_brand_config_cache

        reset_brand_config_cache()
        config_path = tmp_path / "brand_config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "channel_name": "Test Channel",
                    "closing": {"enabled": True, "template": "This is Test Channel."},
                    "cta": {"enabled": True, "template": "Join our journey."},
                    "signature": {"enabled": True, "template": "Breathe and begin."},
                    "branding": {
                        "asset_path": "assets/branding/atma-theory-brand.png",
                        "asset_animation": "slow_zoom",
                    },
                }
            ),
            encoding="utf-8",
        )
        cfg = get_brand_config(config_path=config_path, reload=True)

        try:
            scenes = [
                {"index": 1, "narration": "A philosophical exploration of stillness.", "title": "Intro"},
                {"index": 2, "narration": cfg.closing.text(), "title": "Closing"},
            ]
            _mark_asset_scenes(scenes)

            brand_scene = next(
                (s for s in scenes if s.get("scene_type") == "brand_card"), None
            )
            assert brand_scene is not None, "Expected a brand_card scene to be appended"
            asset_path = brand_scene["asset_path"]

            assert "assets/branding" in asset_path
            assert "workspace/jobs" not in asset_path
            assert asset_path == cfg.branding.asset_path
        finally:
            reset_brand_config_cache()
