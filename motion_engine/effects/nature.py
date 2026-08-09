"""
Nature motion effects: tree_sway, grass_movement, cloud_movement,
waterfall_flow, falling_leaves, birds, butterflies.

All spatial effects (sway, flow) accept an optional mask — figure exclusion
is applied automatically by build_compositor via figure_boxes.
All particle effects accept exclude_mask for the same reason.

RENDERER REUSE PATTERN
When adding cloth_sway, curtain_sway, flag_wave etc., create separate classes
with their own semantically correct names — do not register them as "tree_sway".
They may share the displacement math here (_feather, _remap_blend, the sway
displacement pattern in TreeSway) but must be distinct effect names so that
logs and warnings read "cloth_sway applied" not "tree_sway applied to robe".
"""

import numpy as np
import cv2
from math import sin, cos, pi
from dataclasses import dataclass
from .base import BaseEffect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _feather(mask: np.ndarray, radius: int = 15) -> np.ndarray:
    f = mask.astype(np.float32)
    k = radius * 2 + 1
    return cv2.GaussianBlur(f, (k, k), radius / 2.0)


def _remap_blend(frame: np.ndarray, map_x, map_y, alpha: np.ndarray) -> np.ndarray:
    """Remap entire frame, then blend back using float alpha mask."""
    remapped = cv2.remap(frame, map_x, map_y, cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REFLECT)
    a = alpha[..., np.newaxis]
    result = frame.astype(np.float32) * (1.0 - a) + remapped.astype(np.float32) * a
    return np.clip(result, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# TreeSway
# ---------------------------------------------------------------------------

class TreeSway(BaseEffect):
    """Horizontal sine-wave displacement on vegetation regions."""

    def __init__(
        self,
        mask: np.ndarray = None,    # vegetation region; default upper-right 40%
        intensity: float = 14.0,    # max pixel displacement
        speed: float = 0.8,
        wavelength: float = 120.0,
    ):
        self.mask = mask
        self.intensity = intensity
        self.speed = speed
        self.wavelength = wavelength

    def _get_mask(self, frame):
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        m[:int(h * 0.55), int(w * 0.50):] = True
        return m

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        alpha = _feather(self._get_mask(frame))

        xs = np.arange(w, dtype=np.float32)
        ys = np.arange(h, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(xs, ys)

        # Sway: horizontal displacement varies with height (more at top)
        height_factor = 1.0 - grid_y / h
        disp = self.intensity * height_factor * np.sin(
            2 * np.pi * grid_y / self.wavelength + t * self.speed
        )
        map_x = (grid_x + disp).astype(np.float32)
        map_y = grid_y.astype(np.float32)

        return _remap_blend(frame, map_x, map_y, alpha)


# ---------------------------------------------------------------------------
# GrassMovement
# ---------------------------------------------------------------------------

class GrassMovement(BaseEffect):
    """Subtle horizontal ripple on grass / ground-level vegetation."""

    def __init__(
        self,
        mask: np.ndarray = None,   # default: bottom 30%
        intensity: float = 8.0,
        speed: float = 1.0,
        wavelength: float = 80.0,
    ):
        self.mask = mask
        self.intensity = intensity
        self.speed = speed
        self.wavelength = wavelength

    def _get_mask(self, frame):
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        m[int(h * 0.70):, :] = True
        return m

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        alpha = _feather(self._get_mask(frame))

        xs = np.arange(w, dtype=np.float32)
        ys = np.arange(h, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(xs, ys)

        disp = self.intensity * np.sin(
            2 * np.pi * grid_x / self.wavelength + t * self.speed
        )
        map_x = (grid_x + disp).astype(np.float32)
        map_y = grid_y.astype(np.float32)

        return _remap_blend(frame, map_x, map_y, alpha)


# ---------------------------------------------------------------------------
# CloudMovement
# ---------------------------------------------------------------------------

class CloudMovement(BaseEffect):
    """Slow horizontal drift on sky/cloud region."""

    def __init__(
        self,
        mask: np.ndarray = None,   # default: top 35%
        speed: float = 8.0,        # pixels per second drift
        direction: float = 1.0,    # 1=right, -1=left
    ):
        self.mask = mask
        self.speed = speed
        self.direction = direction

    def _get_mask(self, frame):
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        m[:int(h * 0.35), :] = True
        return m

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        alpha = _feather(self._get_mask(frame), radius=20)

        xs = np.arange(w, dtype=np.float32)
        ys = np.arange(h, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(xs, ys)

        shift = (t * self.speed * self.direction) % w
        map_x = (grid_x - shift).astype(np.float32)
        map_y = grid_y.astype(np.float32)

        return _remap_blend(frame, map_x, map_y, alpha)


# ---------------------------------------------------------------------------
# WaterfallFlow
# ---------------------------------------------------------------------------

class WaterfallFlow(BaseEffect):
    """Vertical downward displacement simulating flowing water."""

    def __init__(
        self,
        mask: np.ndarray = None,
        intensity: float = 5.0,
        speed: float = 1.2,
        wavelength: float = 40.0,
    ):
        self.mask = mask
        self.intensity = intensity
        self.speed = speed
        self.wavelength = wavelength

    def _get_mask(self, frame):
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        m[int(h * 0.20):int(h * 0.85), int(w * 0.35):int(w * 0.65)] = True
        return m

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        alpha = _feather(self._get_mask(frame))

        xs = np.arange(w, dtype=np.float32)
        ys = np.arange(h, dtype=np.float32)
        grid_x, grid_y = np.meshgrid(xs, ys)

        # Downward flow + horizontal shimmer
        disp_y = self.intensity * np.sin(
            2 * np.pi * grid_x / self.wavelength + t * self.speed
        ) + (t * self.speed * 15) % h
        disp_x = self.intensity * 0.3 * np.sin(
            2 * np.pi * grid_y / (self.wavelength * 2) + t * self.speed * 0.7
        )

        map_x = (grid_x + disp_x).astype(np.float32)
        map_y = (grid_y + disp_y).astype(np.float32)

        return _remap_blend(frame, map_x, map_y, alpha)


# ---------------------------------------------------------------------------
# FallingLeaves
# ---------------------------------------------------------------------------

@dataclass
class _Leaf:
    x_start: float
    y_start: float
    vx: float
    vy: float
    size: int
    wobble_freq: float
    color: tuple
    spin_freq: float


class FallingLeaves(BaseEffect):
    """Falling autumn leaves — warm colors, gentle tumbling drift."""

    LEAF_COLORS = [
        (30, 100, 200),   # orange
        (20, 80, 180),    # dark orange
        (15, 140, 210),   # amber
        (10, 60, 160),    # rust
        (40, 120, 190),   # golden
    ]

    def __init__(
        self,
        count: int = 40,
        region_top: float = 0.0,
        region_bottom: float = 1.0,
        alpha: float = 0.55,
        fall_speed: float = 0.4,
        seed: int = 99,
        exclude_mask: np.ndarray = None,
    ):
        self.alpha = alpha
        self.exclude_mask = exclude_mask

        rng = np.random.default_rng(seed)
        self.leaves = [
            _Leaf(
                x_start=float(rng.uniform(0, 1920)),
                y_start=float(rng.uniform(region_top, region_bottom) * 1080),
                vx=float(rng.uniform(-0.8, 0.8)),
                vy=float(rng.uniform(fall_speed * 0.5, fall_speed + 0.2)),
                size=int(rng.integers(2, 6)),
                wobble_freq=float(rng.uniform(0.4, 1.2)),
                color=FallingLeaves.LEAF_COLORS[int(rng.integers(0, len(FallingLeaves.LEAF_COLORS)))],
                spin_freq=float(rng.uniform(0.5, 2.0)),
            )
            for _ in range(count)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = frame.copy()

        for leaf in self.leaves:
            x = int(leaf.x_start + leaf.vx * t * 40 + sin(t * leaf.wobble_freq) * 15) % w
            y = int(leaf.y_start + leaf.vy * t * 35) % h
            size = max(1, leaf.size + int(sin(t * leaf.spin_freq) * 1))
            cv2.circle(overlay, (x, y), size, leaf.color, -1)

        if self.exclude_mask is not None and self.exclude_mask.shape[:2] == (h, w):
            overlay[self.exclude_mask] = frame[self.exclude_mask]

        return cv2.addWeighted(frame, 1.0, overlay, self.alpha, 0)


# ---------------------------------------------------------------------------
# Birds
# ---------------------------------------------------------------------------

@dataclass
class _Bird:
    x_start: float
    y: float
    speed: float
    size: int
    wing_freq: float


class Birds(BaseEffect):
    """Small birds flying across the sky — simple V-shapes."""

    def __init__(
        self,
        count: int = 6,
        region_top: float = 0.05,
        region_bottom: float = 0.35,
        color: tuple = (20, 20, 20),
        alpha: float = 0.70,
        speed: float = 0.04,
        seed: int = 77,
        exclude_mask: np.ndarray = None,
    ):
        self.color = color
        self.alpha = alpha
        self.exclude_mask = exclude_mask

        rng = np.random.default_rng(seed)
        self.birds = [
            _Bird(
                x_start=float(rng.uniform(-0.2, 0.8) * 1920),
                y=float(rng.uniform(region_top, region_bottom) * 1080),
                speed=float(rng.uniform(speed * 0.6, speed * 1.4)),
                size=int(rng.integers(3, 7)),
                wing_freq=float(rng.uniform(1.5, 3.0)),
            )
            for _ in range(count)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = frame.copy()

        for bird in self.birds:
            x = int(bird.x_start + bird.speed * t * w) % w
            y = int(bird.y + sin(t * 0.3 + bird.x_start) * 8)
            # wing flap: V-shape width varies with sine
            wing = bird.size + int(sin(t * bird.wing_freq) * bird.size * 0.5)
            # draw V: two lines from center
            cv2.line(overlay, (x, y), (x - wing, y - wing // 2), self.color, 1)
            cv2.line(overlay, (x, y), (x + wing, y - wing // 2), self.color, 1)

        if self.exclude_mask is not None and self.exclude_mask.shape[:2] == (h, w):
            overlay[self.exclude_mask] = frame[self.exclude_mask]

        return cv2.addWeighted(frame, 1.0, overlay, self.alpha, 0)


# ---------------------------------------------------------------------------
# Butterflies
# ---------------------------------------------------------------------------

@dataclass
class _Butterfly:
    x_start: float
    y_start: float
    vx: float
    vy: float
    size: int
    color: tuple
    phase: float


class Butterflies(BaseEffect):
    """Colourful butterflies drifting with sinusoidal paths."""

    COLORS = [
        (180, 100, 255),  # purple
        (50, 200, 255),   # yellow
        (100, 200, 100),  # green
        (200, 150, 50),   # blue
    ]

    def __init__(
        self,
        count: int = 8,
        region_top: float = 0.10,
        region_bottom: float = 0.70,
        alpha: float = 0.60,
        drift_speed: float = 0.02,
        seed: int = 55,
        exclude_mask: np.ndarray = None,
    ):
        self.alpha = alpha
        self.exclude_mask = exclude_mask

        rng = np.random.default_rng(seed)
        self.butterflies = [
            _Butterfly(
                x_start=float(rng.uniform(0, 1920)),
                y_start=float(rng.uniform(region_top, region_bottom) * 1080),
                vx=float(rng.uniform(-0.3, 0.3)),
                vy=float(rng.uniform(-0.1, 0.1)),
                size=int(rng.integers(3, 7)),
                color=Butterflies.COLORS[int(rng.integers(0, len(Butterflies.COLORS)))],
                phase=float(rng.uniform(0, 2 * pi)),
            )
            for _ in range(count)
        ]

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = frame.copy()

        for b in self.butterflies:
            x = int(b.x_start + b.vx * t * 60 + sin(t * 0.8 + b.phase) * 30) % w
            y = int(b.y_start + b.vy * t * 30 + cos(t * 1.2 + b.phase) * 20) % h
            # two wing dots
            cv2.circle(overlay, (x - b.size, y), b.size, b.color, -1)
            cv2.circle(overlay, (x + b.size, y), b.size, b.color, -1)
            cv2.circle(overlay, (x, y), max(1, b.size // 2), (30, 30, 30), -1)

        if self.exclude_mask is not None and self.exclude_mask.shape[:2] == (h, w):
            overlay[self.exclude_mask] = frame[self.exclude_mask]

        return cv2.addWeighted(frame, 1.0, overlay, self.alpha, 0)
