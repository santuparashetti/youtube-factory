import numpy as np
import cv2
from .base import BaseEffect


def _smoothstep(p: float) -> float:
    """Ease-in-out: no sudden start/stop, eliminates perceived jitter."""
    p = max(0.0, min(1.0, p))
    return p * p * (3.0 - 2.0 * p)


def _zoom_warp(frame: np.ndarray, zoom: float, cx: float, cy: float) -> np.ndarray:
    """
    Sub-pixel zoom via warpAffine — avoids integer crop rounding that causes jitter.
    zoom > 1 = push in (crop in). cx/cy are fractional center [0,1].
    """
    h, w = frame.shape[:2]
    # translate so zoom center → origin, scale, translate back
    M = np.array([
        [zoom, 0.0, cx * w * (1.0 - zoom)],
        [0.0, zoom, cy * h * (1.0 - zoom)],
    ], dtype=np.float64)
    return cv2.warpAffine(frame, M, (w, h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REFLECT)


class SlowPushIn(BaseEffect):
    def __init__(
        self,
        zoom_start: float = 1.0,
        zoom_end: float = 1.15,
        duration: float = 14.0,
        center_x: float = 0.5,
        center_y: float = 0.5,
    ):
        self.zoom_start = zoom_start
        self.zoom_end = zoom_end
        self.duration = duration
        self.center_x = center_x
        self.center_y = center_y

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        progress = _smoothstep(t / self.duration)
        zoom = self.zoom_start + (self.zoom_end - self.zoom_start) * progress
        return _zoom_warp(frame, zoom, self.center_x, self.center_y)


class SlowPullOut(BaseEffect):
    def __init__(
        self,
        zoom_start: float = 1.15,
        zoom_end: float = 1.0,
        duration: float = 14.0,
        center_x: float = 0.5,
        center_y: float = 0.5,
    ):
        self.zoom_start = zoom_start
        self.zoom_end = zoom_end
        self.duration = duration
        self.center_x = center_x
        self.center_y = center_y

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        progress = _smoothstep(t / self.duration)
        zoom = self.zoom_start + (self.zoom_end - self.zoom_start) * progress
        zoom = max(zoom, 1.0)
        return _zoom_warp(frame, zoom, self.center_x, self.center_y)
