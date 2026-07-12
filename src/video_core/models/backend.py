"""Backend selection: CUDA → MPS → CPU."""

from __future__ import annotations

from .models import Backend


def select_backend(preferred_order: list[str] | None = None) -> Backend:
    """Return the best available compute backend.

    Order: CUDA → MPS → CPU.  Callers may restrict preferred_order to
    a subset supported by a specific model.
    """
    order = [b.lower() for b in (preferred_order or ["cuda", "mps", "cpu"])]

    for b in order:
        if b == "cuda" and _cuda_available():
            return Backend.CUDA
        if b == "mps" and _mps_available():
            return Backend.MPS
        if b == "cpu":
            return Backend.CPU

    return Backend.CPU


def _cuda_available() -> bool:
    try:
        import torch  # type: ignore[import-not-found]
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _mps_available() -> bool:
    try:
        import torch  # type: ignore[import-not-found]
        return bool(
            hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        )
    except Exception:
        return False


def describe_backend(backend: Backend) -> str:
    return {
        Backend.CUDA: "NVIDIA GPU (CUDA)",
        Backend.MPS: "Apple Silicon (MPS)",
        Backend.CPU: "CPU",
    }.get(backend, "CPU")
