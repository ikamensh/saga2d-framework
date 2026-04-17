"""Collision primitives — AABB overlap check and a lightweight Rect.

iter-43's ``dodge`` example surfaced the fact that saga2d shipped no
collision helper at all. Every game that needs hit detection had to
roll its own inline. iter-44 fills the gap with the two smallest
primitives that cover 90% of 2D collision cases:

*   :class:`Rect` — a centre-anchored ``(cx, cy, w, h)`` record with
    an ``overlaps()`` method.
*   :func:`aabb_overlap` — a free function that takes two
    ``(cx, cy, w, h)`` quads (or :class:`Rect` s) and returns a bool.

Both are centre-anchored because saga2d's :class:`Sprite` positions
are its visual anchor — for the default ``BOTTOM_CENTER`` anchor a
sprite's *physical* centre is offset from its position, but in
practice an AABB centred on ``(sprite.x, sprite.y - h/2)`` is within
a pixel or two of the visual centre for most sprites. The
:meth:`saga2d.Sprite.aabb` shortcut does this conversion for the
common case.

For sloped/rotating geometry, polygonal hit tests, pixel-perfect
masks: that's a future library. AABB on the sprite's visual box
is the 80/20 answer for top-down arcade gameplay.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True, slots=True)
class Rect:
    """Centre-anchored axis-aligned bounding box.

    ``cx, cy`` is the centre of the rectangle; ``w, h`` are its full
    dimensions. A sprite at ``position=(100, 100)`` with
    ``SpriteAnchor.CENTER`` and a 40×40 image has
    ``Rect(cx=100, cy=100, w=40, h=40)``.
    """

    cx: float
    cy: float
    w: float
    h: float

    def overlaps(self, other: Union["Rect", tuple[float, float, float, float]]) -> bool:
        """Return ``True`` if this Rect overlaps *other* (another Rect
        or a ``(cx, cy, w, h)`` tuple)."""
        if isinstance(other, Rect):
            ox, oy, ow, oh = other.cx, other.cy, other.w, other.h
        else:
            ox, oy, ow, oh = other
        return (
            abs(self.cx - ox) * 2 < (self.w + ow)
            and abs(self.cy - oy) * 2 < (self.h + oh)
        )

    def contains_point(self, x: float, y: float) -> bool:
        """Return ``True`` if ``(x, y)`` is inside this Rect."""
        return (
            self.cx - self.w / 2 <= x <= self.cx + self.w / 2
            and self.cy - self.h / 2 <= y <= self.cy + self.h / 2
        )


RectLike = Union[Rect, tuple[float, float, float, float]]


def aabb_overlap(a: RectLike, b: RectLike, *, strict: bool = False) -> bool:
    """Return ``True`` iff the two AABBs overlap.

    Both arguments accept a :class:`Rect` or a centre-anchored tuple
    ``(cx, cy, w, h)``. The check is the classic one-dimensional-
    separation-per-axis test: a pair of AABBs overlap iff the
    distance between their centres on each axis is less than the
    sum of their half-extents on that axis.

    ``strict=False`` (default, saga2d convention since iter-44):
    AABBs whose edges exactly touch are **not** considered
    overlapping. Tile-based games placing square tiles edge-to-edge
    don't trigger spurious self-collisions.

    ``strict=True``: edges that touch *are* considered overlapping.
    Bullet-vs-player in shoot'em-ups often wants a bullet tangent to
    the player's edge to tag as a hit on the first contact frame.

    >>> aabb_overlap((0, 0, 10, 10), (8, 0, 10, 10))
    True
    >>> aabb_overlap((0, 0, 10, 10), (10, 0, 10, 10))   # touching edges
    False
    >>> aabb_overlap((0, 0, 10, 10), (10, 0, 10, 10), strict=True)
    True
    >>> aabb_overlap((0, 0, 10, 10), (11, 0, 10, 10))
    False
    """
    if isinstance(a, Rect):
        ax, ay, aw, ah = a.cx, a.cy, a.w, a.h
    else:
        ax, ay, aw, ah = a
    if isinstance(b, Rect):
        bx, by, bw, bh = b.cx, b.cy, b.w, b.h
    else:
        bx, by, bw, bh = b
    if strict:
        return (
            abs(ax - bx) * 2 <= (aw + bw)
            and abs(ay - by) * 2 <= (ah + bh)
        )
    return (
        abs(ax - bx) * 2 < (aw + bw)
        and abs(ay - by) * 2 < (ah + bh)
    )
