"""Anchor / Layout enums and the pure layout math behind them."""

from enum import Enum


class Anchor(Enum):
    CENTER = "center"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    TOP_CENTER = "top"
    BOTTOM_CENTER = "bottom"
    LEFT_CENTER = "left"
    RIGHT_CENTER = "right"


class Layout(Enum):
    NONE = "none"
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


def compute_anchor_position(
    anchor: Anchor, px: int, py: int, pw: int, ph: int, cw: int, ch: int, margin: int | tuple[int, int] = 0,
) -> tuple[int, int]:
    """Top-left of a ``cw × ch`` child anchored inside parent rect ``(px, py, pw, ph)``;
    *margin* insets from the anchored edges, as one value or ``(x, y)``."""
    mx, my = (margin, margin) if isinstance(margin, int) else margin
    name = anchor.value
    if name in ("center", "top", "bottom"):
        x = px + (pw - cw) // 2
    elif name.endswith("right"):
        x = px + pw - cw - mx
    else:
        x = px + mx
    if name in ("center", "left", "right"):
        y = py + (ph - ch) // 2
    elif name.startswith("bottom"):
        y = py + ph - ch - my
    else:
        y = py + my
    return (x, y)


def compute_flow_layout(
    layout: Layout, px: int, py: int, pw: int, ph: int,
    sizes: list[tuple[int, int]], spacing: int = 0, padding: int = 0,
) -> list[tuple[int, int]]:
    """Top-left positions of children laid out in a row or column, centred on the cross axis."""
    result: list[tuple[int, int]] = []
    if layout == Layout.VERTICAL:
        y = py + padding
        for cw, ch in sizes:
            result.append((px + (pw - cw) // 2, y))
            y += ch + spacing
    elif layout == Layout.HORIZONTAL:
        x = px + padding
        for cw, ch in sizes:
            result.append((x, py + (ph - ch) // 2))
            x += cw + spacing
    return result


def compute_content_size(layout: Layout, sizes: list[tuple[int, int]], spacing: int = 0, padding: int = 0) -> tuple[int, int]:
    if layout == Layout.NONE or not sizes:
        return (2 * padding, 2 * padding)
    gaps = (len(sizes) - 1) * spacing
    if layout == Layout.VERTICAL:
        return (max(w for w, _ in sizes) + 2 * padding, sum(h for _, h in sizes) + gaps + 2 * padding)
    return (sum(w for w, _ in sizes) + gaps + 2 * padding, max(h for _, h in sizes) + 2 * padding)
