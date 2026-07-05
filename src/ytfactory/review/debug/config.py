"""Configuration for Video Review Debug Mode V1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DebugLevel(str, Enum):
    """Controls how much diagnostic data the debug collector captures."""

    OFF = "off"
    BASIC = "basic"
    DETAILED = "detailed"
    VERBOSE = "verbose"


@dataclass
class DebugConfig:
    """Configuration for the debug collector."""

    level: DebugLevel = DebugLevel.OFF
