import numpy as np
import cv2
from .base import BaseEffect


class WaterRipple(BaseEffect):
    def __init__(
        self,
        mask: np.ndarray = None,
        intensity: float = 3.0,
        speed: float = 1.0,
        wavelength: float = 60.0,
    ):
        self.mask = mask
        self.intensity = intensity
        self.speed = speed
        self.wavelength = wavelength

    def _get_mask(self, frame: np.ndarray) -> np.ndarray:
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        m[int(h * 0.65):, :] = True
        return m

    def _feather_mask(self, mask: np.ndarray, radius: int = 5) -> np.ndarray:
        """Convert bool mask to float [0,1] with soft edges via Gaussian blur."""
        if mask.dtype == bool or mask.max() <= 1:
            f = mask.astype(np.float32)
        else:
            f = (mask / 255.0).astype(np.float32)
        # blur radius must be odd
        k = radius * 2 + 1
        return cv2.GaussianBlur(f, (k, k), radius / 2.0)

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        raw_mask = self._get_mask(frame)

        # soft float mask — no hard edge, no boundary jitter
        alpha = self._feather_mask(raw_mask)  # (H, W) float32 in [0,1]

        xs = np.arange(w, dtype=np.float32)
        ys = np.arange(h, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(xs, ys)

        tau = 2 * np.pi
        disp_x = self.intensity * np.sin(tau * grid_y / self.wavelength + t * self.speed * 2)
        disp_y = self.intensity * np.sin(tau * grid_x / self.wavelength + t * self.speed * 1.3)

        map_x = (grid_x + disp_x).astype(np.float32)
        map_y = (grid_y + disp_y).astype(np.float32)

        rippled = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        # smooth per-pixel blend: original × (1-α) + rippled × α
        a = alpha[..., np.newaxis]  # (H, W, 1) for broadcasting
        result = (frame.astype(np.float32) * (1.0 - a) + rippled.astype(np.float32) * a)
        return np.clip(result, 0, 255).astype(np.uint8)
