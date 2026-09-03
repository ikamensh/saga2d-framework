"""Axis-aligned rectangles and overlap tests for simple collision checks."""

from __future__ import annotations

from dataclasses import dataclass




@dataclass(frozen=True)
class Rect:
    """Centre-based rectangle: ``(cx, cy)`` centre, ``w × h`` size."""

    cx: float
    cy: float
    w: float
    h: float

    @property
    def left(self) -> float:
        return self.cx - self.w / 2

    @property
    def right(self) -> float:
        return self.cx + self.w / 2

    @property
    def top(self) -> float:
        return self.cy - self.h / 2

    @property
    def bottom(self) -> float:
        return self.cy + self.h / 2

    def overlaps(self, other: Rect | tuple[float, float, float, float], *, strict: bool = False) -> bool:
        return aabb_overlap(self, other, strict=strict)

    def contains_point(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


def _as_rect(value: Rect | tuple[float, float, float, float]) -> Rect:
    return value if isinstance(value, Rect) else Rect(*value)


def aabb_overlap(a: Rect | tuple[float, float, float, float], b: Rect | tuple[float, float, float, float], *, strict: bool = False) -> bool:
    """True when the rectangles overlap.  Touching edges count unless *strict*."""
    ra, rb = _as_rect(a), _as_rect(b)
    if strict:
        return ra.left < rb.right and rb.left < ra.right and ra.top < rb.bottom and rb.top < ra.bottom
    return ra.left <= rb.right and rb.left <= ra.right and ra.top <= rb.bottom and rb.top <= ra.bottom
