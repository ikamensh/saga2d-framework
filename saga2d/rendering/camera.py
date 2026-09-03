"""Camera — a zoomable viewport into the world.  Pure math.

``(x, y)`` is the world position at the viewport's top-left corner::

    screen = (world - (x, y)) * zoom
    world  = screen / zoom + (x, y)

The game loop hands the camera to the backend every frame; sprites in
world space are transformed on the GPU, so scrolling costs nothing per
sprite.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from saga2d.util.tween import Ease

if TYPE_CHECKING:
    from saga2d.input import InputEvent
    from saga2d.rendering.sprite import Sprite

_DEFAULT_KEY_BINDINGS: dict[str, tuple[str, ...]] = {
    "left": ("left",), "right": ("right",), "up": ("up",), "down": ("down",),
}


class Camera:
    """Parameters:
        viewport_size: ``(width, height)`` of the logical screen.
        world_bounds:  Optional ``(left, top, right, bottom)`` the view is
                       clamped inside.
        zoom:          Initial zoom (1 = one world unit per logical pixel).
        min_zoom / max_zoom: Clamp range for :attr:`zoom`.
    """

    def __init__(
        self,
        viewport_size: tuple[int, int],
        *,
        world_bounds: tuple[float, float, float, float] | None = None,
        zoom: float = 1.0,
        min_zoom: float = 0.25,
        max_zoom: float = 4.0,
    ) -> None:
        self._vw, self._vh = int(viewport_size[0]), int(viewport_size[1])
        self._x = 0.0
        self._y = 0.0
        self._zoom = 1.0
        self._min_zoom = min_zoom
        self._max_zoom = max_zoom
        self._world_bounds = world_bounds
        self._follow_target: Sprite | None = None
        self._edge_margin = 0
        self._edge_speed = 0.0
        self._key_speed = 0.0
        self._key_bindings: dict[str, tuple[str, ...]] = {}
        self._held: set[str] = set()
        self._pan_tweens: list[int] = []
        self._tween_manager: Any = None
        self._shake_intensity = 0.0
        self._shake_duration = 0.0
        self._shake_elapsed = 0.0
        self._shake_decay = 1.0
        self._shake_dx = 0.0
        self._shake_dy = 0.0
        self.zoom = zoom

    # -- Properties ------------------------------------------------------------

    @property
    def x(self) -> float:
        return self._x

    @property
    def y(self) -> float:
        return self._y

    @property
    def zoom(self) -> float:
        return self._zoom

    @zoom.setter
    def zoom(self, value: float) -> None:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"zoom must be a positive finite number, got {value!r}")
        self._zoom = max(self._min_zoom, min(self._max_zoom, float(value)))
        self._clamp()

    @property
    def viewport_width(self) -> int:
        return self._vw

    @property
    def viewport_height(self) -> int:
        return self._vh

    @property
    def world_bounds(self) -> tuple[float, float, float, float] | None:
        return self._world_bounds

    @world_bounds.setter
    def world_bounds(self, value: tuple[float, float, float, float] | None) -> None:
        if value is not None:
            left, top, right, bottom = value
            if left > right or top > bottom:
                raise ValueError(f"world_bounds must satisfy left<=right and top<=bottom, got {value}")
        self._world_bounds = value
        self._clamp()

    @property
    def shake_offset(self) -> tuple[float, float]:
        return (self._shake_dx, self._shake_dy)

    @property
    def center(self) -> tuple[float, float]:
        return (self._x + self._vw / 2 / self._zoom, self._y + self._vh / 2 / self._zoom)

    # -- Positioning -----------------------------------------------------------

    def center_on(self, x: float, y: float) -> None:
        """Centre the view on world ``(x, y)``.  Cancels pan and follow."""
        self._cancel_pan()
        self._follow_target = None
        self._x = x - self._vw / 2 / self._zoom
        self._y = y - self._vh / 2 / self._zoom
        self._clamp()

    def follow(self, sprite: Sprite | None) -> None:
        self._cancel_pan()
        self._follow_target = sprite

    def scroll(self, dx: float, dy: float) -> None:
        """Move the view by ``(dx, dy)`` world units."""
        self._cancel_pan()
        self._follow_target = None
        self._x += dx
        self._y += dy
        self._clamp()

    def zoom_at(self, factor: float, sx: float, sy: float) -> None:
        """Multiply zoom by *factor* keeping screen point ``(sx, sy)`` fixed."""
        wx, wy = self.screen_to_world(sx, sy)
        self._cancel_pan()
        self.zoom = self._zoom * factor
        self._x = wx - sx / self._zoom
        self._y = wy - sy / self._zoom
        self._clamp()

    def pan_to(self, x: float, y: float, duration: float, ease: Ease = Ease.EASE_IN_OUT) -> None:
        """Smoothly move the view centre to ``(x, y)`` over *duration* seconds."""
        from saga2d.util import tween as tween_mod

        self._tween_manager = tween_mod._tween_manager
        self._cancel_pan()
        self._follow_target = None
        target_x = x - self._vw / 2 / self._zoom
        target_y = y - self._vh / 2 / self._zoom
        target_x, target_y = self._clamped(target_x, target_y)
        self._pan_tweens = [
            tween_mod.tween(self, "_x", self._x, target_x, duration, ease=ease),
            tween_mod.tween(self, "_y", self._y, target_y, duration, ease=ease, on_complete=self._pan_done),
        ]

    # -- Scrolling modes -------------------------------------------------------

    def enable_edge_scroll(self, margin: int, speed: float) -> None:
        self._edge_margin = margin
        self._edge_speed = speed

    def disable_edge_scroll(self) -> None:
        self._edge_speed = 0.0

    def enable_key_scroll(self, speed: float = 600, bindings: dict[str, tuple[str, ...]] | None = None) -> None:
        """Scroll while direction keys are held.  *bindings* maps
        ``"left"/"right"/"up"/"down"`` to key names (default: arrows)."""
        self._key_speed = speed
        self._key_bindings = dict(bindings or _DEFAULT_KEY_BINDINGS)

    def disable_key_scroll(self) -> None:
        self._key_speed = 0.0
        self._held.clear()

    def handle_input(self, event: InputEvent) -> bool:
        """Track direction keys for key scroll.  Returns True if consumed."""
        if not self._key_speed or event.key is None:
            return False
        for direction, keys in self._key_bindings.items():
            if event.key in keys:
                if event.type == "key_press":
                    self._held.add(direction)
                elif event.type == "key_release":
                    self._held.discard(direction)
                return True
        return False

    # -- Shake -----------------------------------------------------------------

    def shake(self, intensity: float, duration: float, decay: float = 1.0) -> None:
        self._shake_intensity = intensity
        self._shake_duration = duration
        self._shake_elapsed = 0.0
        self._shake_decay = decay
        self._shake_dx = self._shake_dy = 0.0

    # -- Conversion ------------------------------------------------------------

    @property
    def offset(self) -> tuple[float, float]:
        """Effective top-left world position including shake."""
        return (self._x + self._shake_dx, self._y + self._shake_dy)

    def screen_to_world(self, sx: float, sy: float) -> tuple[float, float]:
        ox, oy = self.offset
        return (sx / self._zoom + ox, sy / self._zoom + oy)

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        ox, oy = self.offset
        return ((wx - ox) * self._zoom, (wy - oy) * self._zoom)

    def visible_world_rect(self) -> tuple[float, float, float, float]:
        """``(left, top, right, bottom)`` of the world currently in view."""
        ox, oy = self.offset
        return (ox, oy, ox + self._vw / self._zoom, oy + self._vh / self._zoom)

    # -- Per-frame update --------------------------------------------------------

    def update(self, dt: float, mouse: tuple[float, float] | None = None) -> None:
        target = self._follow_target
        if target is not None:
            if target.is_removed:
                self._follow_target = None
            else:
                tx, ty = target.position
                self._x = tx - self._vw / 2 / self._zoom
                self._y = ty - self._vh / 2 / self._zoom
                self._clamp()

        if self._edge_speed and mouse is not None:
            mx, my = mouse
            m = self._edge_margin
            step = self._edge_speed * dt / self._zoom
            dx = -step if mx < m else step if mx > self._vw - m else 0.0
            dy = -step if my < m else step if my > self._vh - m else 0.0
            if dx or dy:
                self._x += dx
                self._y += dy
                self._clamp()

        if self._key_speed and self._held:
            step = self._key_speed * dt / self._zoom
            dx = (-step if "left" in self._held else 0.0) + (step if "right" in self._held else 0.0)
            dy = (-step if "up" in self._held else 0.0) + (step if "down" in self._held else 0.0)
            if dx or dy:
                self._x += dx
                self._y += dy
                self._clamp()

        if self._shake_duration > 0:
            self._shake_elapsed += dt
            if self._shake_elapsed >= self._shake_duration:
                self._shake_duration = 0.0
                self._shake_dx = self._shake_dy = 0.0
            else:
                progress = self._shake_elapsed / self._shake_duration
                amp = self._shake_intensity * (1.0 - progress) ** self._shake_decay
                self._shake_dx = random.uniform(-amp, amp)
                self._shake_dy = random.uniform(-amp, amp)

    # -- Internals -------------------------------------------------------------

    def _clamped(self, x: float, y: float) -> tuple[float, float]:
        if self._world_bounds is None:
            return x, y
        left, top, right, bottom = self._world_bounds
        view_w = self._vw / self._zoom
        view_h = self._vh / self._zoom
        # When the world is smaller than the view, centre it.
        x = (left + right - view_w) / 2 if right - left <= view_w else max(left, min(x, right - view_w))
        y = (top + bottom - view_h) / 2 if bottom - top <= view_h else max(top, min(y, bottom - view_h))
        return x, y

    def _clamp(self) -> None:
        self._x, self._y = self._clamped(self._x, self._y)

    def _cancel_pan(self) -> None:
        if self._tween_manager is not None:
            for tid in self._pan_tweens:
                self._tween_manager.cancel(tid)
        self._pan_tweens = []

    def _pan_done(self) -> None:
        self._pan_tweens = []
        self._clamp()
