import numpy as np
import cv2
from math import sin
from .base import BaseEffect


def _feather_mask(mask: np.ndarray, radius: int = 40) -> np.ndarray:
    """Soft float mask via Gaussian blur — eliminates hard rectangular edges."""
    f = mask.astype(np.float32)
    k = radius * 2 + 1
    return cv2.GaussianBlur(f, (k, k), radius / 2.0)


class LampFlicker(BaseEffect):
    def __init__(
        self,
        mask: np.ndarray = None,
        base_brightness: float = 1.0,
        flicker_intensity: float = 0.18,
    ):
        self.mask = mask
        self.base_brightness = base_brightness
        self.flicker_intensity = flicker_intensity

    def _get_mask(self, frame: np.ndarray) -> np.ndarray:
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        y0 = int(h * 0.35)
        y1 = int(h * 0.65)
        x0 = int(w * 0.35)
        x1 = int(w * 0.65)
        m[y0:y1, x0:x1] = True
        return m

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        raw_mask = self._get_mask(frame)
        alpha = _feather_mask(raw_mask)          # soft float mask, no hard edges

        fi = self.flicker_intensity
        # Natural oil lamp: fast micro + medium pulse + slow breathe
        # ~1 Hz fast, ~0.5 Hz medium, ~0.2 Hz slow — visible but not strobe
        flicker = (
            self.base_brightness
            + fi * 0.6 * sin(t * 7.0)    # fast micro  ~1.1 Hz
            + fi * 0.3 * sin(t * 3.5)    # medium      ~0.56 Hz
            + fi * 0.1 * sin(t * 1.2)    # slow breathe ~0.19 Hz
        )
        flicker = float(np.clip(flicker, 0.68, 1.35))

        base = frame.astype(np.float32)
        brightened = base * flicker

        # warm glow: boost red channel slightly when bright
        if flicker > 1.0:
            warmth = (flicker - 1.0) * 0.5
            brightened[..., 2] = np.clip(brightened[..., 2] * (1.0 + warmth), 0, 255)

        # smooth per-pixel blend using feathered alpha — no rectangle visible
        a = alpha[..., np.newaxis]
        result = base * (1.0 - a) + brightened * a
        return np.clip(result, 0, 255).astype(np.uint8)


class TorchFlicker(BaseEffect):
    """
    Open flame flicker — torch, diya, bonfire.
    More erratic and wider range than kerosene lamp, stronger orange-red warmth.
    """

    def __init__(
        self,
        mask: np.ndarray = None,
        base_brightness: float = 1.0,
        flicker_intensity: float = 0.35,
    ):
        self.mask = mask
        self.base_brightness = base_brightness
        self.flicker_intensity = flicker_intensity

    def _get_mask(self, frame: np.ndarray) -> np.ndarray:
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        m[int(h * 0.30):int(h * 0.70), int(w * 0.35):int(w * 0.65)] = True
        return m

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        raw_mask = self._get_mask(frame)
        alpha = _feather_mask(raw_mask)

        fi = self.flicker_intensity
        # Open flame: faster micro + strong medium + slow breathe — more erratic than lamp
        flicker = (
            self.base_brightness
            + fi * 0.50 * sin(t * 11.0)   # fast erratic ~1.75 Hz
            + fi * 0.30 * sin(t *  5.5)   # medium pulse  ~0.87 Hz
            + fi * 0.20 * sin(t *  1.8)   # slow breathe  ~0.29 Hz
        )
        flicker = float(np.clip(flicker, 0.55, 1.50))  # wider range than lamp

        base = frame.astype(np.float32)
        brightened = base * flicker

        if flicker > 1.0:
            warmth = (flicker - 1.0) * 0.9
            brightened[..., 2] = np.clip(brightened[..., 2] * (1.0 + warmth), 0, 255)       # red
            brightened[..., 1] = np.clip(brightened[..., 1] * (1.0 + warmth * 0.3), 0, 255) # slight green → orange

        a = alpha[..., np.newaxis]
        result = base * (1.0 - a) + brightened * a
        return np.clip(result, 0, 255).astype(np.uint8)


class CandleFlicker(BaseEffect):
    """Candle variant — faster, more erratic flicker than lamp."""

    def __init__(
        self,
        mask: np.ndarray = None,
        base_brightness: float = 1.0,
        flicker_intensity: float = 0.18,
    ):
        self.mask = mask
        self.base_brightness = base_brightness
        self.flicker_intensity = flicker_intensity

    def _get_mask(self, frame: np.ndarray) -> np.ndarray:
        if self.mask is not None:
            return self.mask
        h, w = frame.shape[:2]
        m = np.zeros((h, w), dtype=bool)
        y0 = int(h * 0.3)
        y1 = int(h * 0.6)
        x0 = int(w * 0.4)
        x1 = int(w * 0.6)
        m[y0:y1, x0:x1] = True
        return m

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        raw_mask = self._get_mask(frame)
        alpha = _feather_mask(raw_mask)

        fi = self.flicker_intensity
        flicker = (
            self.base_brightness
            + fi * 0.5 * sin(t * 7.5)    # was 17.3
            + fi * 0.35 * sin(t * 4.0)   # was 9.1
            + fi * 0.15 * sin(t * 1.5)   # was 3.7
        )
        flicker = float(np.clip(flicker, 0.6, 1.4))

        base = frame.astype(np.float32)
        brightened = base * flicker

        if flicker > 1.0:
            warmth = (flicker - 1.0) * 0.6
            brightened[..., 2] = np.clip(brightened[..., 2] * (1.0 + warmth), 0, 255)

        a = alpha[..., np.newaxis]
        result = base * (1.0 - a) + brightened * a
        return np.clip(result, 0, 255).astype(np.uint8)
