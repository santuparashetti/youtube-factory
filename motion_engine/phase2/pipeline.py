"""
Phase 2 Batch Pipeline.

Scans a folder of PNG/JPG images, analyzes each with LLM vision,
renders an animated MP4 for each, and writes a summary report.

Usage:
    python -m motion_engine.phase2.pipeline \\
        --images workspace/jobs/<id>/images/ \\
        --output output/<id>/ \\
        --duration 14

Or from Python:
    from motion_engine.phase2.pipeline import Phase2Pipeline
    pipeline = Phase2Pipeline(images_dir="images/", output_dir="output/")
    pipeline.run()
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import List

from motion_engine import build_compositor
from motion_engine.renderer import Renderer
from motion_engine.phase2.analyzer import SceneAnalyzer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class Phase2Pipeline:
    def __init__(
        self,
        images_dir: str,
        output_dir: str,
        duration: float = 14.0,
        fps: int = 30,
        llm_provider=None,
    ):
        self.images_dir = Path(images_dir)
        self.output_dir = Path(output_dir)
        self.duration = duration
        self.fps = fps
        self.analyzer = SceneAnalyzer(llm_provider=llm_provider)
        self.renderer = Renderer()

    def _collect_images(self) -> List[Path]:
        images = sorted(
            p for p in self.images_dir.iterdir()
            if p.suffix.lower() in IMAGE_EXTENSIONS
        )
        logger.info(f"Found {len(images)} images in {self.images_dir}")
        return images

    def run(self) -> dict:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        images = self._collect_images()

        if not images:
            logger.warning(f"No images found in {self.images_dir}")
            return {"processed": 0, "failed": 0, "results": []}

        results = []
        failed = 0

        for img_path in images:
            result = self._process_one(img_path)
            results.append(result)
            if not result["success"]:
                failed += 1

        summary = {
            "processed": len(images),
            "failed": failed,
            "succeeded": len(images) - failed,
            "results": results,
        }

        summary_path = self.output_dir / "phase2_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2))
        logger.info(f"Phase 2 complete. {summary['succeeded']}/{len(images)} rendered. Summary: {summary_path}")
        return summary

    def _process_one(self, img_path: Path) -> dict:
        stem = img_path.stem
        output_path = str(self.output_dir / f"{stem}-animated.mp4")

        logger.info(f"[{stem}] Analyzing...")
        t0 = time.time()

        try:
            plan = self.analyzer.analyze(str(img_path))

            logger.info(
                f"[{stem}] {plan.scene_type}, {plan.time_of_day}, "
                f"{len(plan.figure_boxes)} figure(s), "
                f"effects: {[e.name for e in plan.effects]}"
            )

            scene = plan.to_scene_config(
                output_path=output_path,
                duration=self.duration,
                fps=self.fps,
            )

            compositor = build_compositor(scene)
            self.renderer.render(scene, compositor)

            elapsed = time.time() - t0
            size_mb = os.path.getsize(output_path) / 1e6
            logger.info(f"[{stem}] Done in {elapsed:.1f}s → {output_path} ({size_mb:.1f} MB)")

            return {
                "image": str(img_path),
                "output": output_path,
                "success": True,
                "scene_type": plan.scene_type,
                "time_of_day": plan.time_of_day,
                "figure_count": len(plan.figure_boxes),
                "effects": [e.name for e in plan.effects],
                "elapsed_seconds": round(elapsed, 1),
                "size_mb": round(size_mb, 1),
            }

        except Exception as e:
            logger.error(f"[{stem}] FAILED: {e}", exc_info=True)
            return {
                "image": str(img_path),
                "output": output_path,
                "success": False,
                "error": str(e),
            }


def main():
    parser = argparse.ArgumentParser(description="Motion Engine Phase 2 — batch scene rendering")
    parser.add_argument("--images", required=True, help="Folder containing scene images")
    parser.add_argument("--output", required=True, help="Output folder for animated MP4s")
    parser.add_argument("--duration", type=float, default=14.0, help="Clip duration in seconds")
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    pipeline = Phase2Pipeline(
        images_dir=args.images,
        output_dir=args.output,
        duration=args.duration,
        fps=args.fps,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
