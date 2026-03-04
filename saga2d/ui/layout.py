"""Layout enums and pure-math helpers for UI positioning and flow."""

from enum import Enum


class Anchor(Enum):
    """Where a component is positioned relative to its parent."""

    CENTER = "center"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class Layout(Enum):
    """How children are arranged inside a container."""

    NONE = "none"
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


def compute_anchor_position(
    anchor: Anchor,
    parent_x: int,
    parent_y: int,
    parent_w: int,
    parent_h: int,
    child_w: int,
    child_h: int,
    margin: int = 0,
) -> tuple[int, int]:
    """Compute top-left (x, y) of a child given its anchor within a parent rect."""
    if anchor == Anchor.CENTER:
        x = parent_x + (parent_w - child_w) // 2
        y = parent_y + (parent_h - child_h) // 2
    elif anchor == Anchor.TOP:
        x = parent_x + (parent_w - child_w) // 2
        y = parent_y + margin
    elif anchor == Anchor.BOTTOM:
        x = parent_x + (parent_w - child_w) // 2
        y = parent_y + parent_h - child_h - margin
    elif anchor == Anchor.LEFT:
        x = parent_x + margin
        y = parent_y + (parent_h - child_h) // 2
    elif anchor == Anchor.RIGHT:
        x = parent_x + parent_w - child_w - margin
        y = parent_y + (parent_h - child_h) // 2
    elif anchor == Anchor.TOP_LEFT:
        x = parent_x + margin
        y = parent_y + margin
    elif anchor == Anchor.TOP_RIGHT:
        x = parent_x + parent_w - child_w - margin
        y = parent_y + margin
    elif anchor == Anchor.BOTTOM_LEFT:
        x = parent_x + margin
        y = parent_y + parent_h - child_h - margin
    elif anchor == Anchor.BOTTOM_RIGHT:
        x = parent_x + parent_w - child_w - margin
        y = parent_y + parent_h - child_h - margin
    else:
        valid = ", ".join(a.name for a in Anchor)
        raise ValueError(f"Unknown anchor: {anchor}; valid values: {valid}")
    return (x, y)


def compute_flow_layout(
    layout: Layout,
    parent_x: int,
    parent_y: int,
    parent_w: int,
    parent_h: int,
    children_sizes: list[tuple[int, int]],
    spacing: int = 0,
    padding: int = 0,
) -> list[tuple[int, int]]:
    """Compute positions for children in a flow layout.

    Returns a list of (x, y) top-left positions for each child.
    Children are centered on the cross-axis.
    """
    if layout == Layout.NONE or not children_sizes:
        return []

    if layout == Layout.VERTICAL:
        result = []
        y = parent_y + padding
        for cw, ch in children_sizes:
            x = parent_x + (parent_w - cw) // 2
            result.append((x, y))
            y += ch + spacing
        return result

    if layout == Layout.HORIZONTAL:
        result = []
        x = parent_x + padding
        for cw, ch in children_sizes:
            y = parent_y + (parent_h - ch) // 2
            result.append((x, y))
            x += cw + spacing
        return result

    valid = ", ".join(lay.name for lay in Layout)
    raise ValueError(f"Unknown layout: {layout}; valid values: {valid}")


def compute_content_size(
    layout: Layout,
    children_sizes: list[tuple[int, int]],
    spacing: int = 0,
    padding: int = 0,
) -> tuple[int, int]:
    """Compute the minimum size needed to contain all children."""
    if layout == Layout.NONE or not children_sizes:
        return (2 * padding, 2 * padding)

    if layout == Layout.VERTICAL:
        width = max(cw for cw, _ in children_sizes) + 2 * padding
        height = (
            sum(ch for _, ch in children_sizes)
            + (len(children_sizes) - 1) * spacing
            + 2 * padding
        )
        return (width, height)

    if layout == Layout.HORIZONTAL:
        height = max(ch for _, ch in children_sizes) + 2 * padding
        width = (
            sum(cw for cw, _ in children_sizes)
            + (len(children_sizes) - 1) * spacing
            + 2 * padding
        )
        return (width, height)

    valid = ", ".join(lay.name for lay in Layout)
    raise ValueError(f"Unknown layout: {layout}; valid values: {valid}")
