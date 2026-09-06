"""Pure geometry for immediate-mode shapes: rounded rectangles and their borders.

Backends fan-triangulate polygons, so every outline here is convex and
listed clockwise on screen (y grows downwards).
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from saga2d.backends.base import Backend, Color, Space

Point = tuple[float, float]


def corner_segments(radius: float) -> int:
    """Arc segments per corner that keep a corner of *radius* smooth."""
    return max(2, min(10, round(radius / 2)))


def _arc_outline(x: float, y: float, w: float, h: float, r: float, segments: int) -> list[Point]:
    corners = (
        ((x + r, y + r), math.pi, 1.5 * math.pi),
        ((x + w - r, y + r), 1.5 * math.pi, 2 * math.pi),
        ((x + w - r, y + h - r), 0.0, 0.5 * math.pi),
        ((x + r, y + h - r), 0.5 * math.pi, math.pi),
    )
    points: list[Point] = []
    for (cx, cy), a0, a1 in corners:
        for i in range(segments + 1):
            a = a0 + (a1 - a0) * i / segments
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return points


@lru_cache(maxsize=1024)
def rounded_rect(x: float, y: float, w: float, h: float, radius: float) -> list[Point]:
    """Outline of the rectangle at top-left ``(x, y)`` with corners of *radius*
    (clamped to half the shorter side).  Cached: a HUD redraws the same panels every frame."""
    r = max(0.0, min(radius, w / 2, h / 2))
    if r == 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    return _arc_outline(x, y, w, h, r, corner_segments(r))


@lru_cache(maxsize=1024)
def rounded_rect_border(x: float, y: float, w: float, h: float, radius: float, width: float) -> list[list[Point]]:
    """Quads forming a border of *width* just inside the rounded rectangle's edge.  Cached like :func:`rounded_rect`."""
    r = max(0.0, min(radius, w / 2, h / 2))
    n = corner_segments(r) if r > 0 else 2
    inset = min(width, w / 2, h / 2)
    outer = _arc_outline(x, y, w, h, r, n)
    inner = _arc_outline(x + inset, y + inset, w - 2 * inset, h - 2 * inset, max(0.0, r - inset), n)
    count = len(outer)
    return [[outer[i], outer[(i + 1) % count], inner[(i + 1) % count], inner[i]] for i in range(count)]


def draw_box(
    backend: Backend, x: float, y: float, w: float, h: float, color: Color, *,
    border_color: Color | None = None, border_width: float = 0, radius: float = 0,
    space: Space = "screen", order: int = 0,
) -> None:
    """Fill a (rounded) rectangle, then its border just inside the edge."""
    if color[3] > 0:
        if radius > 0:
            backend.draw_polygon(rounded_rect(x, y, w, h, radius), color, space=space, order=order)
        else:
            backend.draw_rect(x, y, w, h, color, space=space, order=order)
    if border_color is not None and border_width > 0 and border_color[3] > 0:
        if radius > 0:
            for quad in rounded_rect_border(x, y, w, h, radius, border_width):
                backend.draw_polygon(quad, border_color, space=space, order=order)
        else:
            bw = border_width
            backend.draw_rect(x, y, w, bw, border_color, space=space, order=order)
            backend.draw_rect(x, y + h - bw, w, bw, border_color, space=space, order=order)
            backend.draw_rect(x, y + bw, bw, max(0.0, h - 2 * bw), border_color, space=space, order=order)
            backend.draw_rect(x + w - bw, y + bw, bw, max(0.0, h - 2 * bw), border_color, space=space, order=order)
