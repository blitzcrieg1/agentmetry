"""Correlated behavioral detection over canonical audit events."""

from __future__ import annotations

from .engine import run_detections
from .models import Detection
from .rules import REGISTRY

__all__ = ["run_detections", "Detection", "REGISTRY"]
