import numpy as np
import cv2
from dataclasses import dataclass
from math import sin
from .base import BaseEffect


@dataclass
class _Particle:
    x_start: float
    y_start: float
    vx: float
    vy: float
    size: int
    wobble_freq: float


class DustParticles(BaseEffect):
    def __init__(
        self,
        count: int = 80,
        region_top: float = 0.1,
        region_bottom: float = 0.7,
        color_inner: tuple = (212, 175, 55),   # saturated gold core
        color_mid: tuple = (255, 245, 200),    # warm creamy white
        color_outer: tuple = (255, 255, 240),  # pure white, fades to 0
        max_size: float = 3.5,
        alpha: float = 0.32,
        drift_speed: float = 0.18,
        seed: int = 42,
        exclude_mask: np.ndarray = None,       # bool mask — no particles drawn here
    ):
        self.count = count
        self.region_top = region_top
        self.region_bottom = region_bottom
        self.color_inner = color_inner
        self.color_mid = color_mid
        self.color_outer = color_outer
        self.max_size = max_size
        self.alpha = alpha
        self.drift_speed = drift_speed
        self.exclude_mask = exclude_mask

        rng = np.random.default_rng(seed)
        self.particles = [
            _Particle(
                x_start=float(rng.uniform(0, 1920)),
                y_start=float(rng.uniform(region_top, region_bottom) * 1080),
                vx=float(rng.uniform(-0.5, 0.5)),
                vy=float(rng.uniform(0.1, drift_speed + 0.1)),
                size=int(rng.integers(1, int(max_size) + 1)),
                wobble_freq=float(rng.uniform(0.3, 1.5)),
            )
            for _ in range(count)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = frame.copy()

        for p in self.particles:
            x = int(p.x_start + p.vx * t * 50 + sin(t * p.wobble_freq) * 5) % w
            y = int(p.y_start - p.vy * t * 30) % h
            r = p.size

            # Radial gradient: outer (white) → mid (cream) → inner (gold)
            # Outer edge alpha fades to 0 via the global addWeighted blend.
            cv2.circle(overlay, (x, y), r, self.color_outer, -1)
            if r >= 2:
                cv2.circle(overlay, (x, y), max(1, round(r * 0.65)), self.color_mid, -1)
                cv2.circle(overlay, (x, y), max(1, round(r * 0.30)), self.color_inner, -1)

        # erase any particle pixels that landed on excluded regions (figures)
        if self.exclude_mask is not None:
            em = self.exclude_mask
            if em.shape[:2] == (h, w):
                overlay[em] = frame[em]

        return cv2.addWeighted(frame, 1.0, overlay, self.alpha, 0)


class MistDrift(BaseEffect):
    """
    Atmospheric mist over a configurable rectangular region.

    Region bounds are fractional (0.0–1.0).  Density fades toward the
    inner edges of the region so the mist blends naturally into the scene.

    Default: top-right sky area (x 0.35→1.0, y 0.0→0.50).
    """

    def __init__(
        self,
        opacity: float = 0.15,
        drift_speed: float = 0.08,
        color: tuple = (240, 240, 235),
        # region bounds (fractional, 0.0–1.0)
        x0: float = 0.35,
        x1: float = 1.00,
        y0: float = 0.00,
        y1: float = 0.50,
    ):
        self.opacity = opacity
        self.drift_speed = drift_speed
        self.color = color
        self.x0 = x0
        self.x1 = x1
        self.y0 = y0
        self.y1 = y1

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]

        rx0, rx1 = int(w * self.x0), int(w * self.x1)
        ry0, ry1 = int(h * self.y0), int(h * self.y1)
        rw = max(rx1 - rx0, 1)
        rh = max(ry1 - ry0, 1)

        # 2-D density: fades from dense (top-right corner) toward inner edges
        cols = np.linspace(0.0, 1.0, rw, dtype=np.float32)   # left→right
        rows = np.linspace(1.0, 0.0, rh, dtype=np.float32)   # top→bottom fade

        density = rows[:, None] * cols[None, :]               # (rh, rw)

        color_arr = np.array(self.color, dtype=np.float32)
        mist_patch = density[:, :, None] * color_arr          # (rh, rw, 3)

        mist_layer = np.zeros_like(frame, dtype=np.float32)
        mist_layer[ry0:ry1, rx0:rx1] = mist_patch

        return cv2.addWeighted(
            frame.astype(np.float32), 1.0, mist_layer, self.opacity, 0
        ).clip(0, 255).astype(np.uint8)
