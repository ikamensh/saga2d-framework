"""Minimap — a scaled picture of the world with the camera's viewport drawn over it.

The game keeps the picture up to date (``game.assets.update_image``); the
component draws it, frames the part of the world the camera shows, and
turns clicks and drags into world coordinates::

    self.ui.add(Minimap("minimap", (W * TILE, H * TILE), self.camera, width=200, height=160,
                        on_click=self.minimap_click, anchor=Anchor.BOTTOM_LEFT, margin=12))

``on_click(world_x, world_y, button)`` fires on every press and drag inside
the map; the usual response is ``camera.center_on`` for the left button and
a move order for the right one.  ``pings`` are ``(world_x, world_y, seconds
left)`` markers the game adds for alerts; they shrink as they expire.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from saga2d.rendering.shapes import draw_box
from saga2d.ui.base import Component
from saga2d.ui.theme import Color, Style

if TYPE_CHECKING:
    from saga2d.input import InputEvent
    from saga2d.rendering.camera import Camera

OnClick = Callable[[float, float, str], Any]


class Minimap(Component):
    def __init__(
        self, image: str, world_size: tuple[float, float], camera: Camera, *,
        width: int, height: int, on_click: OnClick | None = None, frame_color: Color = (255, 255, 255, 220),
        style: Style | None = None, **kwargs: Any,
    ) -> None:
        super().__init__(width=width, height=height, style=style, **kwargs)
        self.image = image
        self.world_size = world_size
        self.camera = camera
        self.on_click = on_click
        self.frame_color = frame_color
        self.pings: list[list[float]] = []
        self._dragging = False

    def to_world(self, sx: float, sy: float) -> tuple[float, float]:
        x, y, w, h = self.bounds
        return ((sx - x) / w * self.world_size[0], (sy - y) / h * self.world_size[1])

    def to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        x, y, w, h = self.bounds
        return (x + wx / self.world_size[0] * w, y + wy / self.world_size[1] * h)

    def ping(self, wx: float, wy: float, seconds: float = 4.0) -> None:
        self.pings.append([wx, wy, seconds])

    def update(self, dt: float) -> None:
        for ping in self.pings:
            ping[2] -= dt
        self.pings = [p for p in self.pings if p[2] > 0]

    def on_event(self, event: InputEvent) -> bool:
        inside = self.hit_test(event.x, event.y)
        if event.type == "click" and inside:
            self._dragging = event.button == "left"
            if self.on_click is not None:
                self.on_click(*self.to_world(event.x, event.y), event.button or "left")
            return True
        if event.type == "drag" and self._dragging:
            if inside and self.on_click is not None:
                self.on_click(*self.to_world(event.x, event.y), "left")
            return True
        if event.type == "release" and self._dragging:
            self._dragging = False
            return True
        return False

    def on_draw(self) -> None:
        if self._game is None:
            return
        backend, theme = self._game.backend, self._game.theme
        x, y, w, h = self.bounds
        resolved = theme.resolve_panel_style(self.style)
        order = self._order
        draw_box(backend, x - resolved.border_width, y - resolved.border_width, w + 2 * resolved.border_width, h + 2 * resolved.border_width,
                 resolved.background_color, border_color=resolved.border_color, border_width=resolved.border_width, radius=resolved.radius, order=order)
        backend.draw_image(self._game.assets.image(self.image), x, y, w, h, order=order)
        # The viewport frame and pings sit above the image: images draw over shapes at one order, so use the next.
        above = order + 1
        left, top, right, bottom = self.camera.visible_world_rect()
        sx0, sy0 = self.to_screen(max(0.0, left), max(0.0, top))
        sx1, sy1 = self.to_screen(min(self.world_size[0], right), min(self.world_size[1], bottom))
        draw_box(backend, sx0, sy0, max(2.0, sx1 - sx0), max(2.0, sy1 - sy0), (0, 0, 0, 0), border_color=self.frame_color, border_width=1, order=above)
        for wx, wy, left_s in self.pings:
            px, py = self.to_screen(wx, wy)
            r = 3 + 6 * (left_s % 1.0)
            draw_box(backend, px - r, py - r, 2 * r, 2 * r, (0, 0, 0, 0), border_color=(255, 70, 60, 230), border_width=2, radius=r, order=above)
