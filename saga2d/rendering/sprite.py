"""Sprite — the visible on-screen object backed by the render batch.

A :class:`Sprite` wraps a backend sprite id with properties that automatically
sync to the backend whenever they change.  Game code creates sprites like::

    knight = Sprite("sprites/knight", position=(400, 300))
    knight.position = (500, 350)   # moves on screen immediately
    knight.remove()                # gone from the batch

The Sprite reads ``_current_game`` (a module-level reference set by
:class:`~saga2d.game.Game`) at construction time to obtain the backend and
asset manager.  This keeps the public API clean — no explicit ``game`` arg.

Y-sort draw ordering
--------------------
Draw order is ``layer.value * 100_000 + int(y)``.  Higher y (further down
the screen) produces a larger order value, so it draws later and appears
in front — correct for top-down 2D games.
"""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING, Any, Callable

from saga2d.rendering.layers import RenderLayer, SpriteAnchor
from saga2d.util.tween import Ease

if TYPE_CHECKING:
    from saga2d.actions import Action
    from saga2d.animation import AnimationDef, AnimationPlayer
    from saga2d.rendering.color_swap import ColorSwap

# Module-level reference set by Game.__init__().
# Sprites read this at construction time.
_current_game: Any = None


# ---------------------------------------------------------------------------
# Anchor offset helper
# ---------------------------------------------------------------------------


def _anchor_offset(
    anchor: SpriteAnchor,
    img_w: int,
    img_h: int,
) -> tuple[int, int]:
    """Return ``(dx, dy)`` to subtract from position to get top-left draw corner.

    In the framework's coordinate system (y-down, top-left origin):

    - ``dx``: how far left the top-left corner is from the anchor point.
    - ``dy``: how far up the top-left corner is from the anchor point.

    Example: BOTTOM_CENTER with a 64x64 image at (400, 300)
    → dx=32, dy=64 → draw at (368, 236).
    """
    TL = SpriteAnchor.TOP_LEFT
    TC = SpriteAnchor.TOP_CENTER
    TR = SpriteAnchor.TOP_RIGHT
    CL = SpriteAnchor.CENTER_LEFT
    C = SpriteAnchor.CENTER
    CR = SpriteAnchor.CENTER_RIGHT
    BL = SpriteAnchor.BOTTOM_LEFT
    BC = SpriteAnchor.BOTTOM_CENTER

    # Horizontal
    if anchor in (TL, CL, BL):
        dx = 0
    elif anchor in (TC, C, BC):
        dx = img_w // 2
    else:  # RIGHT variants
        dx = img_w

    # Vertical (y-down: top=0, bottom=height)
    if anchor in (TL, TC, TR):
        dy = 0
    elif anchor in (CL, C, CR):
        dy = img_h // 2
    else:  # BOTTOM variants
        dy = img_h

    return dx, dy


# ---------------------------------------------------------------------------
# Sprite
# ---------------------------------------------------------------------------


class Sprite:
    """A visible game object rendered via the backend batch.

    Parameters:
        image:         Asset name resolved by :meth:`AssetManager.image`.
        position:      ``(x, y)`` logical coordinates.
        anchor:        Where the position point lies on the image.
        layer:         Render layer (back-to-front draw order).
        opacity:       0 (transparent) to 255 (opaque).
        visible:       Whether the sprite is drawn at all.
        tint:          Color tint (r, g, b) in 0.0–1.0. Default (1.0, 1.0, 1.0).
        color_swap:    Optional ColorSwap for per-pixel color replacement.
        team_palette:  Optional registered palette name (e.g. "blue").
                       Ignored if color_swap is set.

    Raises:
        RuntimeError: If created when no Game is active (e.g. after teardown).
    """

    def __init__(
        self,
        image: str,
        *,
        position: tuple[float, float] = (0, 0),
        anchor: SpriteAnchor = SpriteAnchor.BOTTOM_CENTER,
        layer: RenderLayer = RenderLayer.UNITS,
        opacity: int = 255,
        visible: bool = True,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
        color_swap: "ColorSwap | None" = None,
        team_palette: str | None = None,
    ) -> None:
        if _current_game is None:
            raise RuntimeError(
                "No active Game. Create a Game instance before creating Sprites."
            )

        game = _current_game
        self._backend = game.backend
        self._assets = game.assets
        self._game = game
        self._image_name = image

        # Resolve image handle: color_swap > team_palette > plain image
        swap = color_swap
        if swap is None and team_palette is not None:
            from saga2d.rendering.color_swap import get_palette

            swap = get_palette(team_palette)
        if swap is not None:
            self._image_handle = self._assets.image_swapped(image, swap)
        else:
            self._image_handle = self._assets.image(image)
        self._anchor = anchor
        self._layer = layer
        self._x = float(position[0])
        self._y = float(position[1])
        if not (math.isfinite(self._x) and math.isfinite(self._y)):
            raise ValueError(
                f"Sprite position must be finite, got ({self._x}, {self._y})"
            )
        self._opacity = opacity
        self._visible = visible
        self._tint = tint
        self._removed = False

        # Animation state.
        self._anim_player: AnimationPlayer | None = None
        self._anim_queue: deque[tuple[AnimationDef, Callable[[], Any] | None]] = deque()
        self._move_tween_ids: list[int] = []

        # Action state (Stage 10 Composable Actions).
        self._current_action: Action | None = None

        # Scene ownership (set by Scene.add_sprite).
        self._owning_scene: Any = None

        # Cache image dimensions for anchor offset.
        self._img_w, self._img_h = self._backend.get_image_size(
            self._image_handle,
        )

        # Create the backend sprite.
        order = self._compute_order()
        self._last_order: int = order
        self._sprite_id = self._backend.create_sprite(
            self._image_handle,
            order,
        )

        # Register in the game's sprite registry (for camera render sync).
        self._game._all_sprites.add(self)

        # Push initial position + visual state.
        self._sync_to_backend()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def position(self) -> tuple[float, float]:
        """Logical ``(x, y)`` position."""
        return (self._x, self._y)

    @position.setter
    def position(self, value: tuple[float, float] | None) -> None:
        if value is None:
            raise ValueError(
                "Sprite position cannot be None. Use a tuple like (0, 0) instead."
            )
        new_x = float(value[0])
        new_y = float(value[1])
        if not (math.isfinite(new_x) and math.isfinite(new_y)):
            raise ValueError(f"Sprite position must be finite, got ({new_x}, {new_y})")
        if new_x == self._x and new_y == self._y:
            return
        self._x = new_x
        self._y = new_y
        self._sync_to_backend()
        if not self._removed:
            order = self._compute_order()
            if order != self._last_order:
                self._last_order = order
                self._backend.set_sprite_order(self._sprite_id, order)

    @property
    def x(self) -> float:
        return self._x

    @x.setter
    def x(self, value: float) -> None:
        new_x = float(value)
        if not math.isfinite(new_x):
            raise ValueError(
                f"Sprite position must be finite, got ({new_x}, {self._y})"
            )
        if new_x == self._x:
            return
        self._x = new_x
        self._sync_to_backend()

    @property
    def y(self) -> float:
        return self._y

    @y.setter
    def y(self, value: float) -> None:
        new_y = float(value)
        if not math.isfinite(new_y):
            raise ValueError(
                f"Sprite position must be finite, got ({self._x}, {new_y})"
            )
        if new_y == self._y:
            return
        self._y = new_y
        self._sync_to_backend()
        if not self._removed:
            order = self._compute_order()
            if order != self._last_order:
                self._last_order = order
                self._backend.set_sprite_order(self._sprite_id, order)

    @property
    def opacity(self) -> int:
        """Opacity (0 = invisible, 255 = fully opaque)."""
        return self._opacity

    @opacity.setter
    def opacity(self, value: int | float) -> None:
        if not math.isfinite(value):
            value = 0.0 if value < 0 or value != value else 255.0  # -Inf/NaN->0, Inf->255
        self._opacity = max(0, min(255, int(value)))
        self._sync_to_backend()

    @property
    def visible(self) -> bool:
        """Whether the sprite is drawn."""
        return self._visible

    @visible.setter
    def visible(self, value: bool) -> None:
        self._visible = value
        self._sync_to_backend()

    @property
    def tint(self) -> tuple[float, float, float]:
        """Color tint (r, g, b) in 0.0–1.0. Default (1.0, 1.0, 1.0) = no tint."""
        return self._tint

    @tint.setter
    def tint(self, value: tuple[float, float, float]) -> None:
        self._tint = (
            max(0.0, min(1.0, value[0])),
            max(0.0, min(1.0, value[1])),
            max(0.0, min(1.0, value[2])),
        )
        self._sync_to_backend()

    @property
    def layer(self) -> RenderLayer:
        """Render layer."""
        return self._layer

    @property
    def anchor(self) -> SpriteAnchor:
        """Sprite anchor point."""
        return self._anchor

    @property
    def image(self) -> str:
        """The current asset name.

        Setting this property changes the displayed image immediately::

            sprite.image = "sprites/knight_hit"
        """
        return self._image_name

    @image.setter
    def image(self, name: str) -> None:
        if self._removed:
            return
        handle = self._assets.image(name)
        self._image_name = name
        self._set_image(handle)

    @property
    def image_handle(self) -> Any:
        """The opaque backend image handle (read-only)."""
        return self._image_handle

    @property
    def sprite_id(self) -> Any:
        """The opaque backend sprite id (read-only, for testing)."""
        return self._sprite_id

    # ------------------------------------------------------------------
    # Composable Actions
    # ------------------------------------------------------------------

    def do(self, action: Action) -> None:
        """Start an action sequence, cancelling any current action.

        The sprite is registered in ``Game._action_sprites`` and its
        :meth:`update_action` will be called each frame.
        """
        if self._removed:
            return
        self.stop_actions()
        self._current_action = action
        action.start(self)
        self._game._action_sprites.add(self)

    def stop_actions(self) -> None:
        """Cancel the current action sequence (if any)."""
        if self._current_action is not None:
            self._current_action.stop()
            self._current_action = None
        self._game._action_sprites.discard(self)

    def update_action(self, dt: float) -> None:
        """Advance the current action by *dt* seconds.

        Called automatically by :meth:`Game._update_actions` each frame.
        When the action completes, the sprite is deregistered.
        """
        if self._current_action is None or self._removed:
            return
        if self._current_action.update(dt):
            self._current_action = None
            self._game._action_sprites.discard(self)

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

    def remove(self) -> None:
        """Remove the sprite from the backend batch.

        Also stops any active action, animation, cancels move tweens, and
        deregisters from the game's sprite sets and owning scene.  Safe to
        call multiple times.
        """
        if self._removed:
            return
        # Stop action before setting _removed so stop() can still access state.
        self.stop_actions()
        self._removed = True
        self._anim_player = None
        self._anim_queue.clear()
        for tid in self._move_tween_ids:
            self._game._tween_manager.cancel(tid)
        self._move_tween_ids.clear()
        # Cancel any remaining tweens targeting this sprite (e.g. from tween()).
        self._game._tween_manager.cancel_by_target(self)
        self._game._animated_sprites.discard(self)
        self._game._all_sprites.discard(self)
        self._game._action_sprites.discard(self)
        # Deregister from owning scene (if any).
        if self._owning_scene is not None:
            self._owning_scene._owned_sprites.discard(self)
            self._owning_scene = None
        self._backend.remove_sprite(self._sprite_id)

    @property
    def is_removed(self) -> bool:
        """Whether :meth:`remove` has been called."""
        return self._removed

    # ------------------------------------------------------------------
    # Animation
    # ------------------------------------------------------------------

    def play(
        self,
        anim: AnimationDef,
        *,
        on_complete: Callable[[], Any] | None = None,
    ) -> None:
        """Start *anim* immediately, replacing any current animation.

        Resolves frame names to image handles via the asset manager, creates
        an :class:`AnimationPlayer`, and registers this sprite for automatic
        updates during :meth:`Game.tick`.

        Parameters:
            anim:        The animation definition to play.
            on_complete: Called once when a non-looping animation finishes.
        """
        if self._removed:
            return

        from saga2d.animation import AnimationPlayer

        handles = self._resolve_frames(anim)

        # Wrap on_complete to drain the queue after the user callback fires.
        def _wrapped_on_complete() -> None:
            if on_complete is not None:
                on_complete()
            self._drain_queue()

        self._anim_queue.clear()
        self._anim_player = AnimationPlayer(
            frames=handles,
            frame_duration=anim.frame_duration,
            loop=anim.loop,
            on_complete=_wrapped_on_complete if not anim.loop else None,
        )

        # Immediately display the first frame.
        self._set_image(self._anim_player.current_frame)

        # Register for automatic updates.
        self._game._animated_sprites.add(self)

    def queue(
        self,
        anim: AnimationDef,
        *,
        on_complete: Callable[[], Any] | None = None,
    ) -> None:
        """Queue *anim* to play after the current animation finishes.

        If nothing is currently playing, starts immediately (equivalent to
        :meth:`play`).
        """
        if self._removed:
            return
        if self._anim_player is None or self._anim_player.is_complete:
            self.play(anim, on_complete=on_complete)
        else:
            self._anim_queue.append((anim, on_complete))

    def stop_animation(self) -> None:
        """Stop playback and clear the queue.

        The sprite stays on its current frame.
        """
        self._anim_player = None
        self._anim_queue.clear()
        self._game._animated_sprites.discard(self)

    def move_to(
        self,
        target_pos: tuple[float, float],
        speed: float,
        *,
        ease: Ease | None = None,
        on_arrive: Callable[[], Any] | None = None,
    ) -> None:
        """Move to *target_pos* at *speed* pixels per second.

        Cancels any in-progress movement. If distance is zero, fires
        *on_arrive* immediately.
        """
        if self._removed:
            return

        from saga2d.util.tween import Ease, tween

        use_ease = Ease.LINEAR if ease is None else ease

        target_x, target_y = float(target_pos[0]), float(target_pos[1])
        dx = target_x - self._x
        dy = target_y - self._y
        distance = math.hypot(dx, dy)

        if distance < 1e-6:
            if on_arrive is not None:
                on_arrive()
            return

        duration = distance / speed

        for tid in self._move_tween_ids:
            self._game._tween_manager.cancel(tid)
        self._move_tween_ids.clear()

        arrived = [False]  # mutable guard — ensures on_arrive fires at most once

        def _on_axis_done() -> None:
            if arrived[0]:
                return
            arrived[0] = True
            self._on_move_arrive(on_arrive)

        tid_x = tween(
            self,
            "x",
            self._x,
            target_x,
            duration,
            ease=use_ease,
            on_complete=_on_axis_done,
        )
        tid_y = tween(
            self,
            "y",
            self._y,
            target_y,
            duration,
            ease=use_ease,
            on_complete=_on_axis_done,
        )
        self._move_tween_ids = [tid_x, tid_y]

    def _on_move_arrive(self, on_arrive: Callable[[], Any] | None) -> None:
        """Called when move tweens complete. Clears _move_tween_ids and fires callback."""
        self._move_tween_ids.clear()
        if on_arrive is not None:
            on_arrive()

    def update_animation(self, dt: float) -> None:
        """Advance the animation player by *dt* seconds.

        Called automatically by :meth:`Game.tick` each frame.  If the frame
        changes, pushes the new image handle to the backend.
        """
        if self._removed or self._anim_player is None:
            return

        new_handle = self._anim_player.update(dt)
        if new_handle is not None:
            self._set_image(new_handle)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_order(self) -> int:
        """Compute the y-sort draw order: ``layer * 100_000 + int(y)``."""
        return self._layer.value * 100_000 + int(self._y)

    def _resolve_frames(self, anim: AnimationDef) -> list[Any]:
        """Resolve an AnimationDef's frame names to image handles."""
        if isinstance(anim.frames, str):
            # Prefix string → discover numbered files via AssetManager.frames().
            names = self._assets.frames(anim.frames)
            return [self._assets.image(n) for n in names]
        else:
            return [self._assets.image(n) for n in anim.frames]

    def _set_image(self, handle: Any) -> None:
        """Swap the displayed image and re-cache dimensions."""
        self._image_handle = handle
        self._img_w, self._img_h = self._backend.get_image_size(handle)
        self._sync_to_backend(image=handle)

    def _drain_queue(self) -> None:
        """Pop the next queued animation and play it, if any."""
        if self._anim_queue:
            next_anim, next_cb = self._anim_queue.popleft()
            self.play(next_anim, on_complete=next_cb)

    def _sync_to_backend(self, *, image: Any | None = None) -> None:
        """Push current visual state to the backend."""
        if self._removed:
            return
        dx, dy = _anchor_offset(self._anchor, self._img_w, self._img_h)
        draw_x = int(self._x - dx)
        draw_y = int(self._y - dy)
        self._backend.update_sprite(
            self._sprite_id,
            draw_x,
            draw_y,
            image=image,
            opacity=self._opacity,
            visible=self._visible,
            tint=self._tint,
        )
