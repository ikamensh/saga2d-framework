"""Render layers and sprite anchors."""

from enum import Enum, IntEnum


class RenderLayer(IntEnum):
    """Fixed back-to-front draw order for world-space content."""

    BACKGROUND = 0
    OBJECTS = 1
    UNITS = 2
    EFFECTS = 3
    UI_WORLD = 4


#: Width of one layer's band in the integer draw order.  Sprites with
#: ``y_sort=True`` add their bottom edge (in world units, in steps of
#: ``Y_SORT_STEP``) inside the band.
LAYER_BAND = 100_000
#: Y-sorted sprites within this many world units of each other share a draw
#: order: every distinct order is a batch group, and a moving sprite changes
#: group each time its order changes, so finer steps cost more per frame.
Y_SORT_STEP = 8


def world_order(layer: RenderLayer, y: float = 0.0) -> int:
    """Draw order for world-space content on *layer* at bottom-edge *y*."""
    return int(layer) * LAYER_BAND + int(y) // Y_SORT_STEP


class SpriteAnchor(Enum):
    """Where a sprite's position point lies on its image."""

    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"
    BOTTOM_RIGHT = "bottom_right"


def anchor_offset(anchor: SpriteAnchor, width: float, height: float) -> tuple[float, float]:
    """``(dx, dy)`` from the top-left corner to the anchor point."""
    name = anchor.value
    if name.endswith("left"):
        dx = 0.0
    elif name.endswith("right"):
        dx = width
    else:
        dx = width / 2
    if name.startswith("top"):
        dy = 0.0
    elif name.startswith("bottom"):
        dy = height
    else:
        dy = height / 2
    return dx, dy
