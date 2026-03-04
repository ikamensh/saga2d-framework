"""Pyglet backend — GPU-accelerated rendering via OpenGL.

This module is **never imported at module level** by the framework.  The
``Game`` class performs a lazy ``from saga2d.backends.pyglet_backend import
PygletBackend`` inside ``if backend == "pyglet"`` so that tests never need
pyglet installed.

Implements the full :class:`~saga2d.backends.base.Backend` protocol.
Stage 1 only exercises lifecycle + events + quit; rendering and audio
methods are stubbed (functional but minimal) and will be fleshed out in
later stages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from saga2d.backends.base import (
    Event,
    KeyEvent,
    MouseEvent,
    WindowEvent,
)

if TYPE_CHECKING:
    import pyglet


def _symbol_to_name(symbol: int) -> str:
    """Convert a pyglet key symbol to a lowercase backend-agnostic name."""
    from pyglet.window import key as pyglet_key

    overrides = {
        pyglet_key._0: "0",
        pyglet_key._1: "1",
        pyglet_key._2: "2",
        pyglet_key._3: "3",
        pyglet_key._4: "4",
        pyglet_key._5: "5",
        pyglet_key._6: "6",
        pyglet_key._7: "7",
        pyglet_key._8: "8",
        pyglet_key._9: "9",
        pyglet_key.ENTER: "return",
    }
    return overrides.get(symbol) or pyglet_key.symbol_string(symbol).lower()


def _button_to_name(button: int) -> str:
    """Convert a pyglet mouse button constant to left/right/middle."""
    from pyglet.window import mouse as pyglet_mouse

    if button == pyglet_mouse.LEFT:
        return "left"
    if button == pyglet_mouse.RIGHT:
        return "right"
    if button == pyglet_mouse.MIDDLE:
        return "middle"
    return "unknown"


def _buttons_to_name(buttons: int) -> str | None:
    """Convert pyglet buttons bitmask to a single button name, or None."""
    from pyglet.window import mouse as pyglet_mouse

    if buttons & pyglet_mouse.LEFT:
        return "left"
    if buttons & pyglet_mouse.RIGHT:
        return "right"
    if buttons & pyglet_mouse.MIDDLE:
        return "middle"
    return None


# ---------------------------------------------------------------------------
# PygletBackend
# ---------------------------------------------------------------------------


class PygletBackend:
    """GPU-accelerated backend using pyglet 2.x.

    Satisfies the :class:`~saga2d.backends.base.Backend` protocol via
    structural subtyping — does **not** inherit from ``Backend``.
    """

    def __init__(self) -> None:
        # Populated by create_window.
        self.window: pyglet.window.Window | None = None
        self.batch: pyglet.graphics.Batch | None = None

        self.logical_width: int = 0
        self.logical_height: int = 0
        self.scale_factor: float = 1.0
        self.offset_x: float = 0.0
        self.offset_y: float = 0.0

        self._event_queue: list[Event] = []

        # Sprite tracking (populated in later stages)
        self._sprites: dict[int, pyglet.sprite.Sprite] = {}
        self._next_sprite_id: int = 0

        # Frame-local text labels, rects, and image sprites (cleared each begin_frame)
        self._text_labels: list[pyglet.text.Label] = []
        self._rect_shapes: list[Any] = []
        self._image_sprites: list[pyglet.sprite.Sprite] = []

        # UI layer groups — per-layer ordering so overlay panels correctly
        # occlude content from scenes below.  Each layer gets two groups:
        # one for rects (backgrounds) and one for text, so backgrounds
        # always render before text within the same layer.
        # Cache: layer_int -> (rect_group, text_group)
        self._ui_layer_groups: dict[int, tuple[pyglet.graphics.Group, pyglet.graphics.Group]] = {}
        self._current_ui_layer: int = 0

    # ==================================================================
    # Coordinate conversion
    # ==================================================================

    def _compute_viewport(
        self,
        logical_w: int,
        logical_h: int,
        physical_w: int,
        physical_h: int,
    ) -> None:
        """Compute scale factor and letterbox/pillarbox offsets."""
        physical_ratio = physical_w / physical_h
        logical_ratio = logical_w / logical_h

        if physical_ratio > logical_ratio:
            # Physical is wider → pillarbox (black bars on sides)
            self.scale_factor = physical_h / logical_h
            self.offset_x = (physical_w - logical_w * self.scale_factor) / 2
            self.offset_y = 0.0
        else:
            # Physical is taller → letterbox (black bars top/bottom)
            self.scale_factor = physical_w / logical_w
            self.offset_x = 0.0
            self.offset_y = (physical_h - logical_h * self.scale_factor) / 2

    def _to_physical(
        self,
        logical_x: float,
        logical_y: float,
    ) -> tuple[float, float]:
        """Convert framework logical coords → pyglet physical coords.

        Includes y-axis flip (framework: top-left origin, y-down;
        pyglet/OpenGL: bottom-left origin, y-up) and scale + offset.
        """
        physical_x = logical_x * self.scale_factor + self.offset_x
        physical_y = (
            self.logical_height - logical_y
        ) * self.scale_factor + self.offset_y
        return physical_x, physical_y

    def _to_logical(
        self,
        physical_x: float,
        physical_y: float,
    ) -> tuple[int, int]:
        """Convert pyglet physical coords → framework logical coords.

        Inverse of :meth:`_to_physical`.
        """
        logical_x = (physical_x - self.offset_x) / self.scale_factor
        logical_y = (
            self.logical_height - (physical_y - self.offset_y) / self.scale_factor
        )
        return int(logical_x), int(logical_y)

    # ==================================================================
    # Backend protocol — lifecycle
    # ==================================================================

    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        fullscreen: bool,
        visible: bool = True,
    ) -> None:
        import pyglet
        import pyglet.event

        self.logical_width = width
        self.logical_height = height

        self.window = pyglet.window.Window(  # type: ignore[abstract]
            width=width,
            height=height,
            caption=title,
            fullscreen=fullscreen,
            vsync=True,
            visible=visible,
        )

        # Persistent batch — NOT recreated per frame.
        self.batch = pyglet.graphics.Batch()

        # Reset UI layer state for the new window.
        self._ui_layer_groups.clear()
        self._current_ui_layer = 0

        # Compute viewport from actual physical window size.
        self._compute_viewport(
            width,
            height,
            self.window.width,
            self.window.height,
        )

        # --- Register event handlers ONCE ---------------------------------
        backend = self  # capture for closures

        @self.window.event
        def on_key_press(symbol: int, modifiers: int) -> bool:
            backend._event_queue.append(
                KeyEvent(type="key_press", key=_symbol_to_name(symbol)),
            )
            return True  # EVENT_HANDLED — prevent pyglet's default ESC-closes-window

        @self.window.event
        def on_key_release(symbol: int, modifiers: int) -> bool:
            backend._event_queue.append(
                KeyEvent(type="key_release", key=_symbol_to_name(symbol)),
            )
            return True

        @self.window.event
        def on_mouse_press(
            x: int,
            y: int,
            button: int,
            modifiers: int,
        ) -> bool:
            lx, ly = backend._to_logical(x, y)
            backend._event_queue.append(
                MouseEvent(
                    type="click",
                    x=lx,
                    y=ly,
                    button=_button_to_name(button),
                ),
            )
            return True

        @self.window.event
        def on_mouse_release(
            x: int,
            y: int,
            button: int,
            modifiers: int,
        ) -> bool:
            lx, ly = backend._to_logical(x, y)
            backend._event_queue.append(
                MouseEvent(
                    type="release",
                    x=lx,
                    y=ly,
                    button=_button_to_name(button),
                ),
            )
            return True

        @self.window.event
        def on_mouse_motion(x: int, y: int, dx: int, dy: int) -> bool:
            lx, ly = backend._to_logical(x, y)
            backend._event_queue.append(
                MouseEvent(type="move", x=lx, y=ly),
            )
            return True

        @self.window.event
        def on_mouse_drag(
            x: int,
            y: int,
            dx: int,
            dy: int,
            buttons: int,
            modifiers: int,
        ) -> bool:
            lx, ly = backend._to_logical(x, y)
            ldx = int(dx / backend.scale_factor)
            ldy = int(dy / backend.scale_factor)
            button = _buttons_to_name(buttons)
            backend._event_queue.append(
                MouseEvent(
                    type="drag",
                    x=lx,
                    y=ly,
                    button=button,
                    dx=ldx,
                    dy=ldy,
                ),
            )
            return True

        @self.window.event
        def on_mouse_scroll(
            x: int,
            y: int,
            scroll_x: float,
            scroll_y: float,
        ) -> bool:
            lx, ly = backend._to_logical(x, y)
            backend._event_queue.append(
                MouseEvent(
                    type="scroll",
                    x=lx,
                    y=ly,
                    dx=int(scroll_x),
                    dy=int(scroll_y),
                ),
            )
            return True

        @self.window.event
        def on_close() -> bool:
            # Prevent pyglet's default window.close().  The framework
            # handles quit via Game.quit() after seeing the WindowEvent.
            backend._event_queue.append(WindowEvent(type="close"))
            return pyglet.event.EVENT_HANDLED

        @self.window.event
        def on_resize(new_width: int, new_height: int) -> None:
            backend._compute_viewport(
                backend.logical_width,
                backend.logical_height,
                new_width,
                new_height,
            )
            backend._event_queue.append(WindowEvent(type="resize"))

    def begin_frame(
        self,
        clear_color: tuple[int, ...] | None = None,
    ) -> None:
        if self.window is None:
            return
        if clear_color is not None:
            import pyglet.gl as gl

            r, g, b = (
                clear_color[0] / 255.0,
                clear_color[1] / 255.0,
                clear_color[2] / 255.0,
            )
            a = clear_color[3] / 255.0 if len(clear_color) > 3 else 1.0
            gl.glClearColor(r, g, b, a)
        self.window.clear()
        # Discard per-frame text labels, rects, and image sprites from the previous frame.
        for label in self._text_labels:
            label.delete()
        self._text_labels.clear()
        for shape in self._rect_shapes:
            shape.delete()
        self._rect_shapes.clear()
        for img_sprite in self._image_sprites:
            img_sprite.delete()
        self._image_sprites.clear()

    def end_frame(self) -> None:
        if self.window is None or self.batch is None:
            return
        self.batch.draw()
        self.window.flip()

    def poll_events(self) -> list[Event]:
        if self.window is not None:
            self.window.dispatch_events()
        events = self._event_queue.copy()
        self._event_queue.clear()
        return events

    def get_dt(self) -> float:
        import pyglet

        return pyglet.clock.tick()

    def quit(self) -> None:
        if self.window is not None:
            self.window.close()
            self.window = None

    # ==================================================================
    # Backend protocol — image / sprite rendering
    # ==================================================================

    def create_solid_color_image(
        self,
        r: int,
        g: int,
        b: int,
        a: int,
        width: int,
        height: int,
    ) -> Any:
        """Create a solid-color image (PygletBackend-specific, for demos)."""
        import pyglet

        pattern = pyglet.image.SolidColorImagePattern((r, g, b, a))
        return pattern.create_image(width, height)

    def load_image(self, path: str) -> Any:
        import pyglet

        return pyglet.image.load(path)

    def load_image_from_pil(self, pil_image: Any) -> Any:
        """Create a pyglet image from a PIL Image (RGBA)."""
        import pyglet

        raw = pil_image.tobytes()
        # PIL is top-down; negative pitch tells pyglet the row order
        img_data = pyglet.image.ImageData(
            pil_image.width,
            pil_image.height,
            "RGBA",
            raw,
            pitch=-pil_image.width * 4,
        )
        return img_data

    def create_sprite(
        self,
        image_handle: Any,
        layer_order: int,
    ) -> int:
        import pyglet

        group = pyglet.graphics.Group(order=layer_order)
        pyg_sprite = pyglet.sprite.Sprite(
            image_handle,
            batch=self.batch,
            group=group,
        )
        # Scale sprite images to match logical→physical mapping.
        pyg_sprite.scale = self.scale_factor
        sid = self._next_sprite_id
        self._next_sprite_id += 1
        self._sprites[sid] = pyg_sprite
        return sid

    def update_sprite(
        self,
        sprite_id: int,
        x: int,
        y: int,
        *,
        image: Any | None = None,
        opacity: int = 255,
        visible: bool = True,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ) -> None:
        phys_x, phys_y = self._to_physical(x, y)
        pyg = self._sprites[sprite_id]
        pyg.x = phys_x
        # _to_physical gives the top-left in pyglet coords (y-up), but
        # pyglet sprites anchor at bottom-left.  Subtract height to fix.
        pyg.y = phys_y - pyg.height
        pyg.opacity = opacity
        pyg.visible = visible
        r, g, b = tint
        pyg.color = (int(r * 255), int(g * 255), int(b * 255))
        if image is not None:
            pyg.image = image

    def remove_sprite(self, sprite_id: int) -> None:
        self._sprites[sprite_id].delete()
        del self._sprites[sprite_id]

    def get_image_size(self, image_handle: Any) -> tuple[int, int]:
        """Return ``(width, height)`` of a loaded pyglet image."""
        return (image_handle.width, image_handle.height)

    def set_sprite_order(self, sprite_id: int, order: int) -> None:
        """Update the draw order of an existing sprite.

        Replaces the sprite's group with a new one at the given *order*.
        """
        import pyglet

        pyg = self._sprites[sprite_id]
        pyg.group = pyglet.graphics.Group(order=order)

    def capture_frame(self) -> Any:
        """Return a PIL Image of the current framebuffer via glReadPixels.

        Call after tick() — reads from the front buffer (the frame just
        displayed). OpenGL returns bottom-up rows; we flip to match the
        framework's top-left origin.
        """
        import ctypes

        from PIL import Image
        from pyglet.gl import (
            GL_BACK_LEFT,
            GL_FRONT_LEFT,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            glReadBuffer,
            glReadPixels,
        )

        w, h = (
            (self.window.width, self.window.height)
            if self.window is not None
            else (self.logical_width, self.logical_height)
        )
        buffer = (ctypes.c_ubyte * (w * h * 4))()
        glReadBuffer(GL_FRONT_LEFT)
        glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buffer)
        glReadBuffer(GL_BACK_LEFT)  # restore default
        data = bytes(buffer)
        return Image.frombytes("RGBA", (w, h), data).transpose(
            Image.Transpose.FLIP_TOP_BOTTOM
        )

    # ==================================================================
    # Backend protocol — UI layer ordering
    # ==================================================================

    def _get_ui_groups(self, layer: int) -> tuple[Any, Any]:
        """Return (rect_group, text_group) for the given UI layer.

        Each layer maps to two pyglet Groups with consecutive orders:
        - rect_group at ``100 + layer * 2``     (backgrounds first)
        - text_group at ``100 + layer * 2 + 1`` (text on top)

        Groups are cached and reused across frames.
        """
        if layer not in self._ui_layer_groups:
            import pyglet

            base_order = 100 + layer * 2
            rect_group = pyglet.graphics.Group(order=base_order)
            text_group = pyglet.graphics.Group(order=base_order + 1)
            self._ui_layer_groups[layer] = (rect_group, text_group)
        return self._ui_layer_groups[layer]

    def set_ui_layer(self, layer: int) -> None:
        """Set the current UI draw layer for subsequent draw_rect/draw_text."""
        self._current_ui_layer = layer

    # ==================================================================
    # Backend protocol — rect and text rendering
    # ==================================================================

    def draw_rect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: tuple[int, int, int, int],
        *,
        opacity: float = 1.0,
    ) -> None:
        if self.batch is None:
            return
        import pyglet

        # Framework (x,y) is top-left; pyglet Rectangle expects bottom-left.
        phys_tl_x, phys_tl_y = self._to_physical(x, y)
        phys_br_x, phys_br_y = self._to_physical(x + width, y + height)
        phys_w = int(phys_br_x - phys_tl_x)
        phys_h = int(phys_tl_y - phys_br_y)  # y-flipped
        r, g, b, a = color
        alpha = int(a * opacity)
        rect_group, _ = self._get_ui_groups(self._current_ui_layer)
        rect = pyglet.shapes.Rectangle(
            int(phys_tl_x),
            int(phys_br_y),
            phys_w,
            phys_h,
            color=(r, g, b, alpha),
            batch=self.batch,
            group=rect_group,
        )
        self._rect_shapes.append(rect)

    def load_font(self, name: str, path: str | None = None) -> str:
        """Register a font from *path* or use system font when path is None."""
        if path is not None:
            import pyglet

            pyglet.font.add_file(path)
        return name

    def draw_text(
        self,
        text: str,
        x: int,
        y: int,
        font_size: int,
        color: tuple[int, int, int, int],
        *,
        font: str | None = None,
        anchor_x: str = "left",
        anchor_y: str = "baseline",
    ) -> None:
        if self.batch is None:
            return
        import pyglet

        font_name = font if font is not None else "sans-serif"
        physical_size = int(font_size * self.scale_factor)
        phys_x, phys_y = self._to_physical(x, y)
        _, text_group = self._get_ui_groups(self._current_ui_layer)
        label = pyglet.text.Label(
            text,
            font_name=font_name,
            font_size=physical_size,
            x=int(phys_x),
            y=int(phys_y),
            color=color,
            anchor_x=anchor_x,  # type: ignore[arg-type]  # protocol uses str, pyglet expects Literal
            anchor_y=anchor_y,  # type: ignore[arg-type]  # protocol uses str, pyglet expects Literal
            batch=self.batch,
            group=text_group,
        )
        self._text_labels.append(label)

    def draw_image(
        self,
        image_handle: Any,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        opacity: float = 1.0,
    ) -> None:
        """Draw an image at ``(x, y)`` scaled to ``(width, height)``.

        Creates a per-frame pyglet Sprite in the UI overlay group.
        The sprite is deleted on the next :meth:`begin_frame`.
        """
        if self.batch is None:
            return
        import pyglet

        # Convert top-left logical → bottom-left physical.
        phys_tl_x, phys_tl_y = self._to_physical(x, y)
        phys_br_x, phys_br_y = self._to_physical(x + width, y + height)
        phys_w = phys_br_x - phys_tl_x
        phys_h = phys_tl_y - phys_br_y  # y-flipped

        rect_group, _ = self._get_ui_groups(self._current_ui_layer)
        sprite = pyglet.sprite.Sprite(
            image_handle,
            x=int(phys_tl_x),
            y=int(phys_br_y),
            batch=self.batch,
            group=rect_group,
        )
        # Scale to requested size.
        sprite.scale_x = phys_w / image_handle.width
        sprite.scale_y = phys_h / image_handle.height
        sprite.opacity = int(opacity * 255)
        self._image_sprites.append(sprite)

    # ==================================================================
    # Backend protocol — audio
    # ==================================================================

    def load_sound(self, path: str) -> Any:
        import pyglet

        return pyglet.media.load(path, streaming=False)

    def play_sound(self, handle: Any, volume: float = 1.0) -> None:
        player = handle.play()
        player.volume = volume

    def load_music(self, path: str) -> Any:
        import pyglet

        return pyglet.media.load(path, streaming=True)

    def play_music(
        self,
        handle: Any,
        *,
        loop: bool = True,
        volume: float = 1.0,
    ) -> Any:
        import pyglet

        player = pyglet.media.Player()
        player.queue(handle)
        player.loop = loop
        player.volume = volume
        player.play()
        return player

    def set_player_volume(self, player_id: Any, volume: float) -> None:
        player_id.volume = volume

    def stop_player(self, player_id: Any) -> None:
        player_id.pause()
        player_id.delete()

    # ==================================================================
    # Backend protocol — cursor
    # ==================================================================

    def set_cursor(
        self,
        image_handle: Any | None,
        hotspot_x: int = 0,
        hotspot_y: int = 0,
    ) -> None:
        """Set a custom cursor image. None restores system default."""
        if self.window is None:
            return
        import pyglet

        if image_handle is None:
            self.window.set_mouse_cursor(None)
            return
        # Pyglet uses y-up for hot_y; framework uses y-down.
        hot_y = image_handle.height - hotspot_y
        cursor = pyglet.window.ImageMouseCursor(
            image_handle,
            hot_x=hotspot_x,
            hot_y=hot_y,
        )
        self.window.set_mouse_cursor(cursor)

    def set_cursor_visible(self, visible: bool) -> None:
        """Show or hide the mouse cursor."""
        if self.window is None:
            return
        self.window.set_mouse_visible(visible)
