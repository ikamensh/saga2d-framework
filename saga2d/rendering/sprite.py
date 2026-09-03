"""Sprite — a retained image on screen, backed by the backend batch.

::

    knight = Sprite("sprites/knight", position=(400, 300))
    knight.position = (500, 350)    # moves immediately
    knight.remove()

Sprites read the active :class:`~saga2d.game.Game` from a module-level
reference, so game code never passes the game around.

Draw order is ``layer * LAYER_BAND`` plus, when ``y_sort=True``, the
sprite's bottom edge — so sprites further down the screen draw in front.
"""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING, Any, Callable

from saga2d.rendering.layers import RenderLayer, SpriteAnchor, anchor_offset, world_order

if TYPE_CHECKING:
    from saga2d.actions import Action
    from saga2d.animation import AnimationDef, AnimationPlayer
    from saga2d.backends.base import Space
    from saga2d.util.collision import Rect

#: Set by :class:`~saga2d.game.Game` while it is alive.
_current_game: Any = None


def _require_game() -> Any:
    if _current_game is None:
        raise RuntimeError("No active Game. Create a Game instance before creating Sprites.")
    return _current_game


class Sprite:
    """A visible image in world (default) or screen space.

    Parameters:
        image:     Asset name resolved by :meth:`AssetManager.image` (file
                   under ``assets/images`` or a key registered with
                   :meth:`AssetManager.image_from_pil`).
        position:  ``(x, y)`` of the anchor point.
        size:      Drawn ``(width, height)`` in logical units.  ``None``
                   draws the image at its pixel size.
        anchor:    Where *position* sits on the image (default centre).
        layer:     Render layer band.
        space:     ``"world"`` (camera-transformed) or ``"screen"``.
        y_sort:    Sort against other sprites in the layer by bottom edge.
        rotation:  Degrees clockwise about the centre.
    """

    def __init__(
        self,
        image: str,
        *,
        position: tuple[float, float] = (0, 0),
        size: tuple[float, float] | None = None,
        anchor: SpriteAnchor = SpriteAnchor.CENTER,
        layer: RenderLayer = RenderLayer.UNITS,
        space: Space = "world",
        y_sort: bool = False,
        opacity: int = 255,
        visible: bool = True,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
        rotation: float = 0.0,
    ) -> None:
        game = _require_game()
        self._game = game
        self._backend = game.backend
        self._assets = game.assets
        self._image_name = image
        self._image_handle = self._assets.image(image)
        self._img_w, self._img_h = self._backend.get_image_size(self._image_handle)
        self._size: tuple[float, float] | None = None if size is None else (float(size[0]), float(size[1]))
        self._anchor = anchor
        self._layer = layer
        self._space: Space = space
        self._y_sort = y_sort
        self._x = float(position[0])
        self._y = float(position[1])
        if not (math.isfinite(self._x) and math.isfinite(self._y)):
            raise ValueError(f"Sprite position must be finite, got ({self._x}, {self._y})")
        self._opacity = max(0, min(255, int(opacity)))
        self._visible = visible
        self._tint = tint
        self._rotation = float(rotation)
        self._removed = False

        self._anim_player: AnimationPlayer | None = None
        self._anim_queue: deque[tuple[AnimationDef, Callable[[], Any] | None]] = deque()
        self._current_action: Action | None = None
        self._owning_scene: Any = None

        self._order = self._compute_order()
        self._sprite_id = self._backend.create_sprite(self._image_handle, self._order, space)
        game._all_sprites.add(self)
        self._sync()

    # -- Geometry ------------------------------------------------------------

    @property
    def position(self) -> tuple[float, float]:
        return (self._x, self._y)

    @position.setter
    def position(self, value: tuple[float, float]) -> None:
        x, y = float(value[0]), float(value[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(f"Sprite position must be finite, got ({x}, {y})")
        if x == self._x and y == self._y:
            return
        self._x, self._y = x, y
        self._sync()
        self._update_order()

    @property
    def x(self) -> float:
        return self._x

    @x.setter
    def x(self, value: float) -> None:
        self.position = (value, self._y)

    @property
    def y(self) -> float:
        return self._y

    @y.setter
    def y(self, value: float) -> None:
        self.position = (self._x, value)

    @property
    def size(self) -> tuple[float, float]:
        """Drawn ``(width, height)`` in logical units."""
        if self._size is not None:
            return self._size
        return (float(self._img_w), float(self._img_h))

    @size.setter
    def size(self, value: tuple[float, float] | None) -> None:
        self._size = None if value is None else (float(value[0]), float(value[1]))
        self._sync()
        self._update_order()

    @property
    def width(self) -> float:
        return self.size[0]

    @property
    def height(self) -> float:
        return self.size[1]

    @property
    def top_left(self) -> tuple[float, float]:
        w, h = self.size
        dx, dy = anchor_offset(self._anchor, w, h)
        return (self._x - dx, self._y - dy)

    @property
    def center(self) -> tuple[float, float]:
        tx, ty = self.top_left
        w, h = self.size
        return (tx + w / 2, ty + h / 2)

    @property
    def aabb(self) -> Rect:
        from saga2d.util.collision import Rect

        cx, cy = self.center
        w, h = self.size
        return Rect(cx=cx, cy=cy, w=w, h=h)

    @property
    def anchor(self) -> SpriteAnchor:
        return self._anchor

    @property
    def layer(self) -> RenderLayer:
        return self._layer

    @property
    def space(self) -> Space:
        return self._space

    # -- Appearance ----------------------------------------------------------

    @property
    def opacity(self) -> int:
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        self._opacity = max(0, min(255, int(value)))
        self._sync()

    @property
    def visible(self) -> bool:
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._visible = bool(value)
        self._sync()

    @property
    def tint(self) -> tuple[float, float, float]:
        return self._tint

    @tint.setter
    def tint(self, value: tuple[float, float, float]) -> None:
        r, g, b = (max(0.0, min(1.0, float(c))) for c in value)
        self._tint = (r, g, b)
        self._sync()

    @property
    def rotation(self) -> float:
        return self._rotation

    @rotation.setter
    def rotation(self, value: float) -> None:
        self._rotation = float(value)
        self._sync()

    @property
    def image(self) -> str:
        """Asset name of the current image."""
        return self._image_name

    @image.setter
    def image(self, name: str) -> None:
        if self._removed:
            return
        self._image_name = name
        self._set_image(self._assets.image(name))

    @property
    def image_handle(self) -> Any:
        return self._image_handle

    @property
    def sprite_id(self) -> Any:
        return self._sprite_id

    @property
    def is_removed(self) -> bool:
        return self._removed

    # -- Actions ---------------------------------------------------------------

    def do(self, action: Action) -> None:
        """Start *action*, cancelling any current one."""
        if self._removed:
            return
        self.stop_actions()
        self._current_action = action
        action.start(self)
        self._game._action_sprites.add(self)

    def stop_actions(self) -> None:
        if self._current_action is not None:
            self._current_action.stop()
            self._current_action = None
        self._game._action_sprites.discard(self)

    def update_action(self, dt: float) -> None:
        if self._current_action is None or self._removed:
            return
        action = self._current_action
        if action.update(dt) and self._current_action is action:
            self._current_action = None
            self._game._action_sprites.discard(self)

    # -- Animation -------------------------------------------------------------

    def play(self, anim: AnimationDef, *, on_complete: Callable[[], Any] | None = None, _from_queue: bool = False) -> None:
        """Play *anim* now, replacing the current animation."""
        if self._removed:
            return
        from saga2d.animation import AnimationPlayer

        frames = self._resolve_frames(anim)

        def _finished() -> None:
            if on_complete is not None:
                on_complete()
            self._drain_queue()

        if not _from_queue:
            self._anim_queue.clear()
        self._anim_player = AnimationPlayer(
            frames=frames, frame_duration=anim.frame_duration, loop=anim.loop,
            on_complete=None if anim.loop else _finished,
        )
        self._set_image(self._anim_player.current_frame)
        self._game._animated_sprites.add(self)

    def queue(self, anim: AnimationDef, *, on_complete: Callable[[], Any] | None = None) -> None:
        """Play *anim* after the current animation finishes."""
        if self._removed:
            return
        if self._anim_player is None or self._anim_player.is_complete:
            self.play(anim, on_complete=on_complete)
        else:
            self._anim_queue.append((anim, on_complete))

    def stop_animation(self) -> None:
        self._anim_player = None
        self._anim_queue.clear()
        self._game._animated_sprites.discard(self)

    def update_animation(self, dt: float) -> None:
        if self._removed or self._anim_player is None:
            return
        handle = self._anim_player.update(dt)
        if handle is not None:
            self._set_image(handle)

    # -- Removal ---------------------------------------------------------------

    def remove(self) -> None:
        """Remove from the batch and every registry.  Idempotent."""
        if self._removed:
            return
        self.stop_actions()
        self._removed = True
        self._anim_player = None
        self._anim_queue.clear()
        self._game._tween_manager.cancel_by_target(self)
        self._game._animated_sprites.discard(self)
        self._game._all_sprites.discard(self)
        if self._owning_scene is not None:
            self._owning_scene._owned_sprites.discard(self)
            self._owning_scene = None
        self._backend.remove_sprite(self._sprite_id)

    # -- Internals -------------------------------------------------------------

    def _compute_order(self) -> int:
        if self._y_sort:
            return world_order(self._layer, self.top_left[1] + self.size[1])
        return world_order(self._layer)

    def _update_order(self) -> None:
        if self._removed or not self._y_sort:
            return
        order = self._compute_order()
        if order != self._order:
            self._order = order
            self._backend.set_sprite_order(self._sprite_id, order)

    def _resolve_frames(self, anim: AnimationDef) -> list[Any]:
        names = self._assets.frames(anim.frames) if isinstance(anim.frames, str) else anim.frames
        return [self._assets.image(n) for n in names]

    def _set_image(self, handle: Any) -> None:
        self._image_handle = handle
        self._img_w, self._img_h = self._backend.get_image_size(handle)
        self._sync(image=handle)

    def _drain_queue(self) -> None:
        if self._anim_queue:
            anim, cb = self._anim_queue.popleft()
            self.play(anim, on_complete=cb, _from_queue=True)

    def _sync(self, *, image: Any | None = None) -> None:
        if self._removed:
            return
        tx, ty = self.top_left
        w, h = self.size
        self._backend.update_sprite(
            self._sprite_id, tx, ty, w, h,
            image=image, opacity=self._opacity, visible=self._visible,
            tint=self._tint, rotation=self._rotation,
        )
