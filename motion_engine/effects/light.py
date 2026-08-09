import numpy as np
import cv2
from math import sin, cos, pi
from .base import BaseEffect


class WarmBloom(BaseEffect):
    """
    Gentle warm bloom — slow sinusoidal boost to HSV saturation and brightness.
    No particles, no masks. Mimics the subtle glow of golden hour or candlelit
    scenes. Use as the single lighting effect for calm, premium documentary style.
    """

    def __init__(self, intensity: float = 0.18, pulse_speed: float = 0.20):
        self.intensity = intensity   # 0.03 (barely visible) to 0.12 (noticeable)
        self.pulse_speed = pulse_speed

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        pulse = self.intensity * (0.8 + 0.2 * sin(t * self.pulse_speed))
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + pulse * 0.4), 0, 255)  # saturation
        hsv[..., 2] = np.clip(hsv[..., 2] * (1.0 + pulse),       0, 255)  # brightness
        return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


class LightHaze(BaseEffect):
    """
    Very subtle warm atmospheric haze — a faint warm veil over the whole frame
    that pulses gently. Softer and warmer than fog_drift. Ideal for sun-drenched
    interiors, temple scenes, or hazy early morning exteriors.
    """

    def __init__(
        self,
        opacity: float = 0.20,
        color: tuple = (200, 215, 235),  # warm white (BGR)
        pulse_speed: float = 0.15,
    ):
        self.opacity = opacity
        self.color = np.array(color, dtype=np.float32)
        self.pulse_speed = pulse_speed

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        pulse = self.opacity * (0.8 + 0.2 * sin(t * self.pulse_speed))
        haze = np.full(frame.shape, self.color, dtype=np.float32)
        result = frame.astype(np.float32) * (1.0 - pulse) + haze * pulse
        return np.clip(result, 0, 255).astype(np.uint8)


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
        base_alpha: float = 0.18,
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
