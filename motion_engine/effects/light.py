import numpy as np
import cv2
from math import sin, cos, pi
from .base import BaseEffect


class SunRays(BaseEffect):
    """
    Soft volumetric light rays radiating from a light source point.
    Works as a full-frame atmospheric effect — no region mask needed.
    Ideal for golden hour, temple interiors, candle light scenes.
    """

    def __init__(
        self,
        source_x: float = 0.10,     # light source X position (0-1)
        source_y: float = 0.12,     # light source Y position (0-1)
        num_rays: int = 12,
        ray_spread: float = 0.55,   # angular spread in radians around base angle
        color: tuple = (80, 160, 230),  # BGR — warm golden
        base_alpha: float = 0.08,
        pulse_speed: float = 0.3,   # how fast rays breathe
        ray_length_scale: float = 1.8,  # multiplier of frame diagonal
        blur_radius: int = 61,      # softness of rays — must be odd
    ):
        self.source_x = source_x
        self.source_y = source_y
        self.num_rays = num_rays
        self.ray_spread = ray_spread
        self.color = color
        self.base_alpha = base_alpha
        self.pulse_speed = pulse_speed
        self.ray_length_scale = ray_length_scale
        self.blur_radius = blur_radius if blur_radius % 2 == 1 else blur_radius + 1

        # fixed ray angles, spread around the dominant direction (lower-right)
        base_angle = pi * 0.15   # roughly toward lower-right for upper-left source
        self._angles = [
            base_angle + ray_spread * (i / (num_rays - 1) - 0.5)
            for i in range(num_rays)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        diagonal = (h**2 + w**2) ** 0.5

        sx = int(w * self.source_x)
        sy = int(h * self.source_y)
        ray_len = int(diagonal * self.ray_length_scale)

        ray_layer = np.zeros((h, w, 3), dtype=np.uint8)

        for i, angle in enumerate(self._angles):
            # each ray pulses slightly out of phase for organic feel
            phase = i * (pi / self.num_rays)
            pulse = 0.7 + 0.3 * sin(t * self.pulse_speed + phase)

            ex = int(sx + ray_len * cos(angle))
            ey = int(sy + ray_len * sin(angle))

            # ray width varies slightly per ray
            thickness = max(2, int(w * 0.025 * (0.6 + 0.4 * sin(phase))))
            brightness = tuple(int(c * pulse) for c in self.color)
            cv2.line(ray_layer, (sx, sy), (ex, ey), brightness, thickness)

        # blur heavily to make rays soft and volumetric
        ray_layer = cv2.GaussianBlur(ray_layer, (self.blur_radius, self.blur_radius), 0)

        # global pulse for the whole ray set
        global_pulse = self.base_alpha * (0.85 + 0.15 * sin(t * self.pulse_speed * 0.7))
        result = cv2.addWeighted(frame, 1.0, ray_layer, global_pulse, 0)
        return result
