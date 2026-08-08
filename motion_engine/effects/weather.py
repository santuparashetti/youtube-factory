"""
Weather effects: rain, snow, fog, smoke.
All accept exclude_mask so figures stay clean.
"""

import numpy as np
import cv2
from math import sin
from dataclasses import dataclass
from .base import BaseEffect


# ---------------------------------------------------------------------------
# Rain
# ---------------------------------------------------------------------------

@dataclass
class _Raindrop:
    x: float
    y_start: float
    speed: float
    length: int
    alpha: float


class Rain(BaseEffect):
    """Diagonal falling rain streaks."""

    def __init__(
        self,
        count: int = 200,
        angle: float = 10.0,        # degrees from vertical (positive = right lean)
        speed: float = 800.0,       # pixels per second fall speed
        length: int = 18,           # streak length in pixels
        color: tuple = (200, 200, 210),
        alpha: float = 0.35,
        seed: int = 11,
        exclude_mask: np.ndarray = None,
    ):
        self.angle_rad = angle * np.pi / 180.0
        self.speed = speed
        self.length = length
        self.color = color
        self.alpha = alpha
        self.exclude_mask = exclude_mask

        rng = np.random.default_rng(seed)
        self.drops = [
            _Raindrop(
                x=float(rng.uniform(0, 1920)),
                y_start=float(rng.uniform(-200, 1080)),
                speed=float(rng.uniform(speed * 0.8, speed * 1.2)),
                length=int(rng.integers(length // 2, length + 1)),
                alpha=float(rng.uniform(0.5, 1.0)),
            )
            for _ in range(count)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = np.zeros_like(frame)

        dx = int(np.sin(self.angle_rad) * self.length)
        dy = int(np.cos(self.angle_rad) * self.length)

        for drop in self.drops:
            y = int(drop.y_start + drop.speed * t) % (h + 200) - 100
            x = int(drop.x + np.sin(self.angle_rad) * drop.speed * t * 0.1) % w
            x2 = x - dx
            y2 = y - dy
            cv2.line(overlay, (x, y), (x2, y2), self.color, 1)

        if self.exclude_mask is not None and self.exclude_mask.shape[:2] == (h, w):
            overlay[self.exclude_mask] = 0

        return cv2.addWeighted(frame, 1.0, overlay, self.alpha, 0)


# ---------------------------------------------------------------------------
# Snow
# ---------------------------------------------------------------------------

@dataclass
class _Snowflake:
    x_start: float
    y_start: float
    vy: float
    wobble_freq: float
    wobble_amp: float
    size: int


class Snow(BaseEffect):
    """Gently falling snowflakes."""

    def __init__(
        self,
        count: int = 120,
        speed: float = 0.25,
        color: tuple = (245, 245, 250),
        max_size: int = 3,
        alpha: float = 0.55,
        seed: int = 22,
        exclude_mask: np.ndarray = None,
    ):
        self.color = color
        self.alpha = alpha
        self.exclude_mask = exclude_mask

        rng = np.random.default_rng(seed)
        self.flakes = [
            _Snowflake(
                x_start=float(rng.uniform(0, 1920)),
                y_start=float(rng.uniform(-50, 1080)),
                vy=float(rng.uniform(speed * 0.5, speed + 0.1)),
                wobble_freq=float(rng.uniform(0.3, 1.0)),
                wobble_amp=float(rng.uniform(5, 20)),
                size=int(rng.integers(1, max_size + 1)),
            )
            for _ in range(count)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = frame.copy()

        for f in self.flakes:
            x = int(f.x_start + sin(t * f.wobble_freq) * f.wobble_amp) % w
            y = int(f.y_start + f.vy * t * 60) % h
            cv2.circle(overlay, (x, y), f.size, self.color, -1)

        if self.exclude_mask is not None and self.exclude_mask.shape[:2] == (h, w):
            overlay[self.exclude_mask] = frame[self.exclude_mask]

        return cv2.addWeighted(frame, 1.0, overlay, self.alpha, 0)


# ---------------------------------------------------------------------------
# Fog
# ---------------------------------------------------------------------------

class Fog(BaseEffect):
    """Dense rolling fog — heavier than MistDrift."""

    def __init__(
        self,
        region_bottom: float = 0.75,
        opacity: float = 0.30,
        drift_speed: float = 0.04,
        color: tuple = (230, 230, 228),
        layers: int = 3,             # multiple fog layers for depth
    ):
        self.region_bottom = region_bottom
        self.opacity = opacity
        self.drift_speed = drift_speed
        self.color = color
        self.layers = layers

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        fog_top = int(h * (1.0 - self.region_bottom))
        result = frame.astype(np.float32)

        color_arr = np.array(self.color, dtype=np.float32)

        for i in range(self.layers):
            phase = i * (2 * np.pi / self.layers)
            speed = self.drift_speed * (1.0 + i * 0.3)
            layer = np.zeros((h, w, 3), dtype=np.float32)

            rows = np.arange(fog_top, h)
            base_density = (rows - fog_top) / max(h - fog_top, 1)
            wave = 0.15 * np.sin(rows * 0.02 + t * speed + phase)
            density = np.clip(base_density + wave, 0, 1)

            layer[fog_top:h] = (density[:, None, None] * color_arr)
            layer_opacity = self.opacity / self.layers * (1.0 + 0.2 * np.sin(t * 0.5 + phase))
            result = result * (1.0 - layer_opacity) + layer * layer_opacity

        return np.clip(result, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------

@dataclass
class _SmokeParticle:
    x_start: float
    y_start: float
    vx: float
    rise_speed: float
    size_start: int
    wobble_freq: float
    phase: float


class Smoke(BaseEffect):
    """Rising smoke particles that expand and fade as they rise."""

    def __init__(
        self,
        source_x: float = 0.5,     # smoke source X (0-1)
        source_y: float = 0.6,     # smoke source Y (0-1)
        count: int = 30,
        color: tuple = (180, 180, 180),
        alpha: float = 0.25,
        rise_speed: float = 0.3,
        spread: float = 0.05,      # horizontal spread from source
        seed: int = 33,
        exclude_mask: np.ndarray = None,
    ):
        self.source_x = source_x
        self.source_y = source_y
        self.color = color
        self.alpha = alpha
        self.exclude_mask = exclude_mask

        rng = np.random.default_rng(seed)
        self.particles = [
            _SmokeParticle(
                x_start=float(rng.uniform(-spread, spread)),
                y_start=float(rng.uniform(0, 0.1)),   # slight y offset from source
                vx=float(rng.uniform(-0.3, 0.3)),
                rise_speed=float(rng.uniform(rise_speed * 0.6, rise_speed + 0.1)),
                size_start=int(rng.integers(5, 15)),
                wobble_freq=float(rng.uniform(0.2, 0.8)),
                phase=float(rng.uniform(0, 2 * np.pi)),
            )
            for _ in range(count)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = frame.copy()
        sx = int(w * self.source_x)
        sy = int(h * self.source_y)

        for p in self.particles:
            age = (t * p.rise_speed + p.phase) % 3.0   # cycle every 3s
            x = int(sx + p.x_start * w + p.vx * age * 30 + sin(age * p.wobble_freq) * 20)
            y = int(sy - age * p.rise_speed * 100 + p.y_start * h) % h
            size = p.size_start + int(age * 8)   # expands as it rises
            fade = max(0.0, 1.0 - age / 3.0)
            color = tuple(int(c * fade) for c in self.color)
            if 0 <= x < w and 0 <= y < h:
                cv2.circle(overlay, (x, y), size, color, -1)

        if self.exclude_mask is not None and self.exclude_mask.shape[:2] == (h, w):
            overlay[self.exclude_mask] = frame[self.exclude_mask]

        return cv2.addWeighted(frame, 1.0, overlay, self.alpha, 0)
