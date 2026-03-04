"""Render layer and sprite anchor enums.

RenderLayer defines the fixed draw order for sprites (back to front).
SpriteAnchor defines where the position point lies on the sprite image.
"""

from enum import Enum, IntEnum


class RenderLayer(IntEnum):
    """Fixed rendering order, back to front.

    Use as the layer_order when creating sprites. Lower values draw behind
    higher values. Within a layer, sprites are typically y-sorted.
    """

    BACKGROUND = 0  # background images, terrain
    OBJECTS = 1  # trees, buildings, environmental objects
    UNITS = 2  # living units, characters, NPCs
    EFFECTS = 3  # spell effects, projectiles, explosions
    UI_WORLD = 4  # health bars above units, selection circles, name labels


class SpriteAnchor(Enum):
    """Where the position point lies on the sprite image.

    BOTTOM_CENTER is the default for top-down games — the "feet" of the
    sprite sit at its position.
    """

    TOP_LEFT = "top_left"
    TOP_CENTER = "top_center"
    TOP_RIGHT = "top_right"
    CENTER_LEFT = "center_left"
    CENTER = "center"
    CENTER_RIGHT = "center_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_CENTER = "bottom_center"  # default — "feet" of the sprite
    BOTTOM_RIGHT = "bottom_right"
