import subprocess
import cv2
from .scene import SceneConfig
from .compositor import Compositor


class Renderer:
    def render(self, scene: SceneConfig, compositor: Compositor) -> str:
        base_frame = cv2.imread(scene.image_path)
        if base_frame is None:
            raise FileNotFoundError(f"Could not load image: {scene.image_path}")
        base_frame = cv2.resize(base_frame, scene.resolution)

        total_frames = int(scene.duration_seconds * scene.fps)

        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-s", f"{scene.resolution[0]}x{scene.resolution[1]}",
            "-pix_fmt", "bgr24",
            "-r", str(scene.fps),
            "-i", "pipe:0",
            "-vcodec", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            scene.output_path,
        ]

        process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        try:
            for frame_idx in range(total_frames):
                t = frame_idx / scene.fps
                frame = compositor.render_frame(base_frame, t)
                process.stdin.write(frame.tobytes())
        finally:
            process.stdin.close()

        process.wait()

        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {process.stderr.read().decode()}")

        return scene.output_path
