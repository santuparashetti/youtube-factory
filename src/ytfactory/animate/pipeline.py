"""
Animate pipeline — motion engine integration.

Runs between generate-images and render. For each scene PNG, calls the
motion engine Phase 2 analyzer (LLM vision → EffectPlan) and renders a
pre-animated MP4 into workspace/jobs/<id>/animated/.

The render stage detects those clips and uses them as video input instead
of the static PNG, skipping zoompan entirely.

Skips:
  - brand_card / asset scene types (no image to animate)
  - scenes whose animated MP4 already exists (idempotent)
  - scenes with no source image (generate-images may have skipped them)

On any per-scene failure, logs an error and continues — the render stage
falls back to the static PNG automatically.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from loguru import logger
from rich.console import Console
from rich.progress import track

from ytfactory.shared.constants import WORKSPACE_DIR
from ytfactory.shared.paths import safe_project_dir

console = Console()


def _audio_duration(project_dir: Path, index: int, fallback: float) -> float:
    """Return scene audio duration (timing.json → ffprobe → fallback)."""
    timing = project_dir / "audio" / f"scene-{index:03d}.timing.json"
    audio = project_dir / "audio" / f"scene-{index:03d}.mp3"

    try:
        data = json.loads(timing.read_text(encoding="utf-8"))
        if data and isinstance(data, list):
            end = float(data[-1]["end"])
            if end > 0.0:
                return end
    except Exception:
        pass

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio),
            ],
            capture_output=True, text=True, check=True, timeout=10,
        )
        dur = float(result.stdout.strip())
        if dur > 0:
            return dur
    except Exception:
        pass

    return fallback


class AnimatePipeline:
    """
    Analyze each scene image with LLM vision and render a pre-animated MP4.

    Output: workspace/jobs/<id>/animated/scene-NNN.mp4
            workspace/jobs/<id>/animated/animated-manifest.json
    """

    def run(self, project_id: str) -> None:
        # Import here so the package stays importable even without motion_engine
        try:
            from motion_engine.phase2.analyzer import SceneAnalyzer
            from motion_engine import build_compositor
            from motion_engine.renderer import Renderer as MotionRenderer
        except ImportError as exc:
            logger.error(
                "motion_engine not available — animate stage skipped: {}", exc
            )
            return

        project_dir = safe_project_dir(project_id, WORKSPACE_DIR)
        images_dir = project_dir / "images"
        output_dir = project_dir / "animated"
        output_dir.mkdir(parents=True, exist_ok=True)

        scene_plan_path = project_dir / "scenes" / "scene-plan.json"
        if not scene_plan_path.is_file():
            logger.warning("animate: scene-plan.json not found — skipping")
            return

        scenes = json.loads(scene_plan_path.read_text(encoding="utf-8"))["scenes"]

        analyzer = SceneAnalyzer()
        renderer = MotionRenderer()

        results: list[dict] = []
        skipped = 0
        failed = 0

        console.print(f"\n[cyan]Animating {len(scenes)} scene(s) with motion engine...[/cyan]\n")

        for scene in track(scenes, description="Animating"):
            index = scene["index"]
            scene_type = scene.get("scene_type", "generated_image")

            # brand_card / asset scenes are handled separately — no motion
            if scene_type in ("asset", "brand_card"):
                skipped += 1
                continue

            image_path = images_dir / f"scene-{index:03d}.png"
            if not image_path.is_file():
                logger.warning("animate: scene-{:03d} image not found — skipping", index)
                skipped += 1
                continue

            output_path = output_dir / f"scene-{index:03d}.mp4"
            if output_path.is_file():
                logger.debug("animate: scene-{:03d} already animated — reusing", index)
                results.append({"scene": index, "status": "reused", "output": str(output_path)})
                skipped += 1
                continue

            duration = _audio_duration(
                project_dir, index,
                fallback=float(scene.get("duration_seconds", 10.0)),
            )

            t0 = time.time()
            try:
                plan = analyzer.analyze(str(image_path))
                logger.info(
                    "animate: scene-{:03d} → {} figure(s), effects: {}",
                    index,
                    len(plan.figure_boxes),
                    [e.name for e in plan.effects],
                )

                scene_config = plan.to_scene_config(
                    output_path=str(output_path),
                    duration=duration,
                    fps=30,
                )
                compositor = build_compositor(scene_config)
                renderer.render(scene_config, compositor)

                elapsed = time.time() - t0
                size_mb = output_path.stat().st_size / 1e6
                logger.info(
                    "animate: scene-{:03d} done in {:.1f}s ({:.1f} MB)",
                    index, elapsed, size_mb,
                )
                results.append({
                    "scene": index,
                    "status": "ok",
                    "output": str(output_path),
                    "effects": [e.name for e in plan.effects],
                    "figure_count": len(plan.figure_boxes),
                    "elapsed_seconds": round(elapsed, 1),
                    "size_mb": round(size_mb, 1),
                })

            except Exception as exc:
                logger.error("animate: scene-{:03d} FAILED: {}", index, exc)
                failed += 1
                results.append({"scene": index, "status": "failed", "error": str(exc)})

        # Write manifest
        manifest = {
            "project_id": project_id,
            "total": len(scenes),
            "succeeded": len([r for r in results if r.get("status") == "ok"]),
            "reused": len([r for r in results if r.get("status") == "reused"]),
            "skipped": skipped,
            "failed": failed,
            "scenes": results,
        }
        (output_dir / "animated-manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        ok = manifest["succeeded"] + manifest["reused"]
        console.print(
            f"[green]✓[/green] Animation complete: "
            f"{ok} animated, {skipped} skipped, {failed} failed\n"
        )
