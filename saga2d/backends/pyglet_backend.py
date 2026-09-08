"""Pyglet backend — GPU rendering via OpenGL.

Imported lazily by :class:`~saga2d.game.Game`; importing it opens pyglet's
display connection, so mock-backend tests never touch this module.

Coordinate handling
-------------------
Framework coordinates are y-down.  Sprites and shapes are handed to pyglet
in *logical y-up* units (``y_up = H - y`` for screen space, ``y_up = -y``
for world space) and a per-group view matrix maps them to physical
pixels — for world space that matrix also carries the camera, so
scrolling and zooming cost nothing per sprite.  Text is rasterised at
physical size and positioned in physical pixels under an identity view
so glyphs stay sharp on HiDPI displays.

Draw order
----------
World content draws before screen content.  Within a space, the integer
``order`` sorts groups; text at an order draws above shapes and sprites
at the same order.  Immediate shapes at one order are one triangle list
in insertion order, so overlapping rects draw in call order.

Audio
-----
Effects and music go through ``pyglet.media``.  With ``SAGA2D_SILENT=1``
(or ``SAGA2D_HEADLESS=1`` — headless implies silent) pyglet's silent audio
driver is selected, so tests and verification scripts exercise the whole
load/play/stop/teardown path without a sound reaching the speakers.  The
driver is chosen when ``pyglet.media`` is first imported, which is why the
option is set at the top of this module.
"""

from __future__ import annotations

import sys
from typing import Any

import pyglet

from saga2d.backends.base import Color, Event, KeyEvent, MouseEvent, Space, WindowEvent, silent_audio

if silent_audio():
    pyglet.options["audio"] = ("silent",)  # must precede the first import of pyglet.media

import pyglet.graphics  # noqa: E402
import pyglet.window  # noqa: E402  must precede pyglet.gl: it initialises the display
from pyglet.gl import GL_BLEND, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, glBlendFunc, glDisable, glEnable  # noqa: E402

_SCREEN_ORDER_BASE = 1_000_000_000

_SHAPE_VERTEX_SRC = """#version 150 core
in vec2 position;
in vec4 colors;
out vec4 vertex_colors;
uniform WindowBlock { mat4 projection; mat4 view; } window;
void main() {
    gl_Position = window.projection * window.view * vec4(position, 0.0, 1.0);
    vertex_colors = colors;
}
"""

_SHAPE_FRAGMENT_SRC = """#version 150 core
in vec4 vertex_colors;
out vec4 final_color;
void main() {
    final_color = vertex_colors;
}
"""


def _symbol_to_name(symbol: int) -> str:
    from pyglet.window import key as pyglet_key

    overrides = {getattr(pyglet_key, f"_{d}"): str(d) for d in range(10)}
    overrides[pyglet_key.ENTER] = "return"
    return overrides.get(symbol) or pyglet_key.symbol_string(symbol).lower()


def _mods_to_kwargs(modifiers: int) -> dict[str, bool]:
    from pyglet.window import key as pyglet_key

    alt_mask = pyglet_key.MOD_ALT | getattr(pyglet_key, "MOD_OPTION", 0)
    meta_mask = getattr(pyglet_key, "MOD_COMMAND", 0) | getattr(pyglet_key, "MOD_WINDOWS", 0)
    return {
        "shift": bool(modifiers & pyglet_key.MOD_SHIFT),
        "ctrl": bool(modifiers & pyglet_key.MOD_CTRL),
        "alt": bool(modifiers & alt_mask),
        "meta": bool(modifiers & meta_mask),
    }


_MAC = sys.platform == "darwin"


def _button_to_name(button: int) -> str | None:
    from pyglet.window import mouse

    if button & mouse.LEFT:
        return "left"
    if button & mouse.RIGHT:
        return "right"
    if button & mouse.MIDDLE:
        return "middle"
    return None


class PygletBackend:
    def __init__(self) -> None:
        self.window: pyglet.window.Window | None = None
        self.batch: pyglet.graphics.Batch | None = None
        self.logical_width = 0
        self.logical_height = 0
        self.scale_factor = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self._clip_rect = (0, 0, 0, 0)
        self.camera: tuple[float, float, float] = (0.0, 0.0, 1.0)
        self._event_queue: list[Event] = []
        self._sprites: dict[int, Any] = {}
        self._sprite_meta: dict[int, tuple[Space, float, float]] = {}  # space, img_w, img_h
        self._next_sprite_id = 0
        self._view_groups: dict[tuple[Space, int], Any] = {}
        self._text_groups: dict[tuple[Space, int], Any] = {}
        self._shape_program: Any = None
        self._soups: dict[tuple[Space, int], tuple[list[float], list[int]]] = {}
        self._soup_lists: list[Any] = []
        self._frame_images: list[Any] = []  # pooled pyglet sprites for draw_image, reused in call order frame to frame
        self._ctrl_click = False  # a Mac Control+click in progress, reported as the right button
        self._frame_images_used = 0
        self._labels: dict[tuple[Any, ...], tuple[Any, int]] = {}
        self._label_uses: dict[tuple[Any, ...], int] = {}
        self._frame = 0
        self._measure_cache: dict[tuple[str, str | None, int], tuple[int, int]] = {}
        self._atlas: Any = None
        self._padded_images: dict[Any, Any] = {}
        self._identity: Any = None
        self._screen_view: Any = None
        self._world_view: Any = None
        self._applied_view: Any = None
        self._players: dict[int, Any] = {}
        self._sound_players: set[int] = set()
        self._next_player_id = 0
        self._windowed_size = (0, 0)

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _compute_viewport(self, physical_w: int, physical_h: int) -> None:
        from pyglet import gl
        from pyglet.math import Mat4, Vec3

        if physical_w <= 0 or physical_h <= 0:  # Minimized surfaces have no usable viewport.
            return
        self.window.switch_to()
        framebuffer_w, framebuffer_h = self.window.get_framebuffer_size()
        gl.glViewport(0, 0, framebuffer_w, framebuffer_h)
        self.window.projection = Mat4.orthogonal_projection(0, physical_w, 0, physical_h, -8192, 8192)
        lw, lh = self.logical_width, self.logical_height
        if physical_w / physical_h > lw / lh:
            self.scale_factor = physical_h / lh
            self.offset_x = (physical_w - lw * self.scale_factor) / 2
            self.offset_y = 0.0
        else:
            self.scale_factor = physical_w / lw
            self.offset_x = 0.0
            self.offset_y = (physical_h - lh * self.scale_factor) / 2
        s = self.scale_factor
        pixel_x, pixel_y = framebuffer_w / physical_w, framebuffer_h / physical_h
        self._clip_rect = (round(self.offset_x * pixel_x), round(self.offset_y * pixel_y),
                           round(lw * s * pixel_x), round(lh * s * pixel_y))
        self._screen_view = Mat4.from_translation(Vec3(self.offset_x, self.offset_y, 0)) @ Mat4.from_scale(Vec3(s, s, 1))
        self._update_world_view()

    def _update_world_view(self) -> None:
        from pyglet.math import Mat4, Vec3

        cx, cy, zoom = self.camera
        self._world_view = (
            self._screen_view
            @ Mat4.from_translation(Vec3(-cx * zoom, self.logical_height + cy * zoom, 0))
            @ Mat4.from_scale(Vec3(zoom, zoom, 1))
        )
        self._applied_view = None

    def _to_physical(self, x: float, y: float, space: Space) -> tuple[float, float]:
        """Framework coords in *space* → physical pixels (y-up)."""
        if space == "world":
            cx, cy, zoom = self.camera
            x, y = (x - cx) * zoom, (y - cy) * zoom
        return x * self.scale_factor + self.offset_x, (self.logical_height - y) * self.scale_factor + self.offset_y

    def _to_logical(self, px: float, py: float) -> tuple[int, int]:
        lx = (px - self.offset_x) / self.scale_factor
        ly = self.logical_height - (py - self.offset_y) / self.scale_factor
        return int(lx), int(ly)

    def _flip(self, y: float, space: Space) -> float:
        return -y if space == "world" else self.logical_height - y

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def screen_size(self) -> tuple[int, int]:
        screen = pyglet.display.get_display().get_default_screen()
        return screen.width, screen.height

    def create_window(self, width: int, height: int, title: str, fullscreen: bool, visible: bool = True) -> None:
        from pyglet.math import Mat4

        self.logical_width = width
        self.logical_height = height
        try:
            config = pyglet.gl.Config(sample_buffers=1, samples=4, double_buffer=True)
            self.window = pyglet.window.Window(
                width=width, height=height, caption=title, resizable=True,
                vsync=True, visible=False, config=config,
            )
        except pyglet.window.NoSuchConfigException:
            self.window = pyglet.window.Window(
                width=width, height=height, caption=title, resizable=True, vsync=True, visible=False,
            )
        self.batch = pyglet.graphics.Batch()
        self._identity = Mat4()
        self._atlas = pyglet.image.atlas.TextureBin(2048, 2048)
        self._shape_program = pyglet.gl.current_context.create_program(
            (_SHAPE_VERTEX_SRC, "vertex"), (_SHAPE_FRAGMENT_SRC, "fragment"),
        )
        self._compute_viewport(self.window.width, self.window.height)
        self._register_handlers()
        self._windowed_size = self.window_size
        if fullscreen:
            self.set_fullscreen(True)
        # Register first so the initial show/focus events enter the game queue.
        self.window.set_visible(visible)

    def _register_handlers(self) -> None:
        window = self.window
        queue = self._event_queue

        @window.event
        def on_key_press(symbol: int, modifiers: int) -> bool:
            queue.append(KeyEvent("key_press", _symbol_to_name(symbol), **_mods_to_kwargs(modifiers)))
            return True  # never fall through to pyglet's ESC-closes-window default

        @window.event
        def on_key_release(symbol: int, modifiers: int) -> bool:
            queue.append(KeyEvent("key_release", _symbol_to_name(symbol), **_mods_to_kwargs(modifiers)))
            return True

        def name_of(button: int, modifiers: int, pressing: bool) -> str | None:
            # A Mac trackpad has no right button: Control+click is the secondary click there, as in
            # every Mac application.  The release and the drag keep the button the press reported.
            from pyglet.window import key

            name = _button_to_name(button)
            if _MAC and name == "left":
                if pressing:
                    self._ctrl_click = bool(modifiers & key.MOD_CTRL)
                if self._ctrl_click:
                    return "right"
            return name

        @window.event
        def on_mouse_press(x: int, y: int, button: int, modifiers: int) -> bool:
            lx, ly = self._to_logical(x, y)
            queue.append(MouseEvent("click", lx, ly, name_of(button, modifiers, True), **_mods_to_kwargs(modifiers)))
            return True

        @window.event
        def on_mouse_release(x: int, y: int, button: int, modifiers: int) -> bool:
            lx, ly = self._to_logical(x, y)
            queue.append(MouseEvent("release", lx, ly, name_of(button, modifiers, False), **_mods_to_kwargs(modifiers)))
            return True

        @window.event
        def on_mouse_motion(x: int, y: int, dx: int, dy: int) -> bool:
            lx, ly = self._to_logical(x, y)
            queue.append(MouseEvent("move", lx, ly))
            return True

        @window.event
        def on_mouse_drag(x: int, y: int, dx: int, dy: int, buttons: int, modifiers: int) -> bool:
            lx, ly = self._to_logical(x, y)
            s = self.scale_factor
            queue.append(MouseEvent("drag", lx, ly, name_of(buttons, modifiers, False), dx=dx / s, dy=-dy / s, **_mods_to_kwargs(modifiers)))
            return True

        @window.event
        def on_mouse_scroll(x: int, y: int, scroll_x: float, scroll_y: float) -> bool:
            lx, ly = self._to_logical(x, y)
            # Trackpads report fractions of a line per event; keep them.
            queue.append(MouseEvent("scroll", lx, ly, dx=float(scroll_x), dy=float(scroll_y)))
            return True

        @window.event
        def on_close() -> bool:
            queue.append(WindowEvent("close"))
            return pyglet.event.EVENT_HANDLED

        @window.event
        def on_activate() -> None:
            queue.append(WindowEvent('activate'))

        @window.event
        def on_deactivate() -> None:
            queue.append(WindowEvent('deactivate'))

        @window.event
        def on_show() -> None:
            queue.append(WindowEvent('show'))

        @window.event
        def on_hide() -> None:
            queue.append(WindowEvent('hide'))

        @window.event
        def on_resize(new_width: int, new_height: int) -> None:
            self._compute_viewport(new_width, new_height)
            queue.append(WindowEvent("resize"))

    def begin_frame(self, clear_color: Color | None = None) -> None:
        from pyglet import gl

        if clear_color is not None:
            r, g, b = (c / 255.0 for c in clear_color[:3])
            gl.glClearColor(r, g, b, 1.0)
        self.window.clear()
        for vlist in self._soup_lists:
            vlist.delete()
        self._soup_lists.clear()
        self._soups.clear()
        for sprite in self._frame_images[:self._frame_images_used]:
            sprite.visible = False
        self._frame_images_used = 0
        self._label_uses.clear()

    def end_frame(self) -> None:
        from pyglet import gl
        from pyglet.gl import GL_TRIANGLES

        self._frame += 1
        for (space, order), (positions, colors) in self._soups.items():
            self._soup_lists.append(self._shape_program.vertex_list(
                len(positions) // 2, GL_TRIANGLES, batch=self.batch, group=self._shape_group(space, order),
                position=("f", positions), colors=("Bn", colors),
            ))
        for key, (label, last_used) in list(self._labels.items()):
            if last_used != self._frame:
                label.delete()
                del self._labels[key]
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glScissor(*self._clip_rect)
        try:
            self.batch.draw()
        finally:
            gl.glDisable(gl.GL_SCISSOR_TEST)
        self.window.flip()

    def poll_events(self) -> list[Event]:
        self.window.dispatch_events()
        # Media events (a Player's ``on_eos``, which loops music and ends an
        # effect) are posted from pyglet's audio thread and delivered only by
        # the platform event loop, which this frame loop replaces.
        pyglet.app.platform_event_loop.dispatch_posted_events()
        for player_id, player in list(self._players.items()):
            if player.source is None:
                self.stop_player(player_id)
        events = self._event_queue.copy()
        self._event_queue.clear()
        return events

    def get_dt(self) -> float:
        return pyglet.clock.tick()

    def quit(self) -> None:
        for player_id in list(self._players):
            self.stop_player(player_id)
        if self.window is not None:
            self.window.close()
            self.window = None

    @property
    def fullscreen(self) -> bool:
        return self.window.fullscreen

    @property
    def window_size(self) -> tuple[int, int]:
        width, height = self.window.get_size()
        # Pyglet's Cocoa platform/scaled modes return backing pixels here but
        # accept content points in set_size/fullscreen recreation. Keep that
        # mismatch inside this adapter; do not change rendering/input units.
        if sys.platform == "darwin" and pyglet.options.dpi_scaling in ("platform", "scaled"):
            return round(width / self.window.scale), round(height / self.window.scale)
        return width, height

    @property
    def windowed_size(self) -> tuple[int, int]:
        return self._windowed_size if self.fullscreen else self.window_size

    def set_fullscreen(self, fullscreen: bool) -> None:
        if fullscreen == self.fullscreen:
            return
        if fullscreen:
            self._windowed_size = self.window_size
            self.window.set_fullscreen(True)
        else:
            self.window.set_fullscreen(False, width=self._windowed_size[0], height=self._windowed_size[1])
        self._compute_viewport(self.window.width, self.window.height)

    def set_window_size(self, width: int, height: int) -> None:
        if self.fullscreen:
            self.window.set_fullscreen(False, width=width, height=height)
        else:
            self.window.set_size(width, height)
        self._windowed_size = self.window_size
        self._compute_viewport(self.window.width, self.window.height)

    def get_clipboard_text(self) -> str:
        return self.window.get_clipboard_text()

    def set_clipboard_text(self, text: str) -> None:
        self.window.set_clipboard_text(text)

    def capture_frame(self) -> Any:
        """PIL image of the frame most recently presented by :meth:`end_frame`."""
        import ctypes

        from PIL import Image
        from pyglet.gl import GL_BACK_LEFT, GL_FRONT_LEFT, GL_RGBA, GL_UNSIGNED_BYTE, glReadBuffer, glReadPixels

        w, h = self.window.width, self.window.height
        buffer = (ctypes.c_ubyte * (w * h * 4))()
        glReadBuffer(GL_FRONT_LEFT)
        glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buffer)
        glReadBuffer(GL_BACK_LEFT)
        return Image.frombytes("RGBA", (w, h), bytes(buffer)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    def set_camera(self, x: float, y: float, zoom: float) -> None:
        self.camera = (x, y, zoom)
        self._update_world_view()

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def _view_group(self, space: Space, order: int) -> Any:
        key = (space, order)
        group = self._view_groups.get(key)
        if group is None:
            group = _ViewGroup(self, space, _group_order(space, order))
            self._view_groups[key] = group
        return group

    def _shape_group(self, space: Space, order: int) -> Any:
        return _ShaderChild(self._shape_program, self._view_group(space, order))

    def _text_group(self, space: Space, order: int) -> Any:
        key = (space, order)
        group = self._text_groups.get(key)
        if group is None:
            group = _TextGroup(self, _group_order(space, order) + 1)
            self._text_groups[key] = group
        return group

    def _apply_view(self, view: Any) -> None:
        """Upload the view matrix only when it changes: hundreds of groups share two matrices."""
        if self._applied_view is not view:
            self.window.view = view
            self._applied_view = view

    # ------------------------------------------------------------------
    # Images and sprites
    # ------------------------------------------------------------------

    def _atlas_add(self, image_data: Any) -> Any:
        if image_data.width > 1024 or image_data.height > 1024:
            region = image_data.get_texture()
        else:
            # Transparent-black atlas padding darkens opaque tile edges under
            # linear filtering, even when an identical tile lies underneath.
            # Extrude edge colours and keep the public region at its true size.
            padded = self._atlas.add(_extruded_image(image_data))
            region = padded.get_region(1, 1, image_data.width, image_data.height)
            self._padded_images[region] = padded
        region.anchor_x = region.width / 2
        region.anchor_y = region.height / 2
        return region

    def load_image(self, path: str) -> Any:
        return self._atlas_add(pyglet.image.load(path))

    def load_image_from_pil(self, pil_image: Any) -> Any:
        return self._atlas_add(_image_data(pil_image))

    def update_image(self, image_handle: Any, pil_image: Any) -> None:
        if (pil_image.width, pil_image.height) != (image_handle.width, image_handle.height):
            raise ValueError(f"update_image: got {pil_image.size}, the image is {image_handle.width}x{image_handle.height}")
        padded = self._padded_images.get(image_handle)
        if padded is not None:
            padded.blit_into(_extruded_image(_image_data(pil_image)), 0, 0, 0)
        else:
            image_handle.blit_into(_image_data(pil_image), 0, 0, 0)

    def get_image_size(self, image_handle: Any) -> tuple[int, int]:
        return image_handle.width, image_handle.height

    def create_sprite(self, image_handle: Any, order: int, space: Space) -> int:
        sprite = pyglet.sprite.Sprite(image_handle, batch=self.batch, group=_ImageChild(self._view_group(space, order)))
        sid = self._next_sprite_id
        self._next_sprite_id += 1
        self._sprites[sid] = sprite
        self._sprite_meta[sid] = (space, image_handle.width, image_handle.height)
        return sid

    def update_sprite(self, sprite_id: int, x: float, y: float, width: float, height: float, *, image=None,
                      opacity: int = 255, visible: bool = True, tint=(1.0, 1.0, 1.0), rotation: float = 0.0) -> None:
        sprite = self._sprites[sprite_id]
        space, img_w, img_h = self._sprite_meta[sprite_id]
        if image is not None:
            sprite.image = image
            img_w, img_h = image.width, image.height
            self._sprite_meta[sprite_id] = (space, img_w, img_h)
        sprite.update(
            x=x + width / 2, y=self._flip(y + height / 2, space), rotation=rotation,
            scale_x=width / img_w, scale_y=height / img_h,
        )
        # Each pyglet setter rewrites vertex data through ctypes; a moving unit only changes its position.
        if sprite.opacity != opacity:
            sprite.opacity = opacity
        if sprite.visible != visible:
            sprite.visible = visible
        color = (int(tint[0] * 255), int(tint[1] * 255), int(tint[2] * 255))
        if sprite.color != color:
            sprite.color = color

    def set_sprite_order(self, sprite_id: int, order: int) -> None:
        space = self._sprite_meta[sprite_id][0]
        self._sprites[sprite_id].group = _ImageChild(self._view_group(space, order))

    def remove_sprite(self, sprite_id: int) -> None:
        self._sprites.pop(sprite_id).delete()
        del self._sprite_meta[sprite_id]

    # ------------------------------------------------------------------
    # Immediate-mode shapes
    # ------------------------------------------------------------------

    def _soup(self, space: Space, order: int) -> tuple[list[float], list[int]]:
        soup = self._soups.get((space, order))
        if soup is None:
            soup = ([], [])
            self._soups[(space, order)] = soup
        return soup

    def _push_triangles(self, space: Space, order: int, points: list[tuple[float, float]], color: Color) -> None:
        """Fan-triangulate *points* (framework coords) into the soup."""
        positions, colors = self._soup(space, order)
        n = len(points) - 2
        if n <= 0:
            return
        flipped = [(px, self._flip(py, space)) for px, py in points]
        x0, y0 = flipped[0]
        for i in range(1, len(flipped) - 1):
            x1, y1 = flipped[i]
            x2, y2 = flipped[i + 1]
            positions.extend((x0, y0, x1, y1, x2, y2))
        colors.extend(color * (3 * n))

    def draw_rect(self, x, y, width, height, color, *, space: Space = "screen", order: int = 0) -> None:
        self._push_triangles(space, order, [(x, y), (x + width, y), (x + width, y + height), (x, y + height)], color)

    def draw_circle(self, x, y, radius, color, *, space: Space = "screen", order: int = 0) -> None:
        import math

        physical_radius = radius * self.scale_factor * (self.camera[2] if space == "world" else 1.0)
        segments = max(12, min(96, int(physical_radius) + 8))
        step = 2 * math.pi / segments
        rim = [(x + radius * math.cos(i * step), y + radius * math.sin(i * step)) for i in range(segments)]
        positions, colors = self._soup(space, order)
        cx, cy = x, self._flip(y, space)
        flipped = [(px, self._flip(py, space)) for px, py in rim]
        for i in range(segments):
            x1, y1 = flipped[i]
            x2, y2 = flipped[(i + 1) % segments]
            positions.extend((cx, cy, x1, y1, x2, y2))
        colors.extend(color * (3 * segments))

    def draw_line(self, x1, y1, x2, y2, color, width=1.0, *, space: Space = "screen", order: int = 0) -> None:
        import math

        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            return
        nx, ny = -dy / length * width / 2, dx / length * width / 2
        self._push_triangles(space, order, [(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)], color)

    def draw_polygon(self, points, color, *, space: Space = "screen", order: int = 0) -> None:
        self._push_triangles(space, order, list(points), color)

    def draw_image(self, image_handle, x, y, width, height, *, opacity=1.0, space: Space = "screen", order: int = 0) -> None:
        # A HUD draws the same images in the same order every frame: the pooled sprite
        # keeps its vertex list and group, so this is a position update, not an allocation.
        group = _ImageChild(self._view_group(space, order))
        if self._frame_images_used < len(self._frame_images):
            sprite = self._frame_images[self._frame_images_used]
            if sprite.image is not image_handle:
                sprite.image = image_handle
            if sprite.group != group:
                sprite.group = group
            sprite.visible = True
        else:
            sprite = pyglet.sprite.Sprite(image_handle, batch=self.batch, group=group)
            self._frame_images.append(sprite)
        self._frame_images_used += 1
        sprite.update(x=x + width / 2, y=self._flip(y + height / 2, space), scale_x=width / image_handle.width, scale_y=height / image_handle.height)
        alpha = int(opacity * 255)
        if sprite.opacity != alpha:
            sprite.opacity = alpha

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def _physical_font_size(self, font_size: int, space: Space) -> int:
        zoom = self.camera[2] if space == "world" else 1.0
        return max(1, round(font_size * self.scale_factor * zoom))

    def draw_text(self, text, x, y, font_size, color, *, font=None, anchor_x="left", anchor_y="baseline",
                  space: Space = "screen", order: int = 0) -> None:
        px, py = self._to_physical(x, y, space)
        size = self._physical_font_size(font_size, space)
        base_key = (text, font, size, tuple(color), anchor_x, anchor_y, space, order)
        use = self._label_uses.get(base_key, 0)
        self._label_uses[base_key] = use + 1
        key = base_key + (use,)
        entry = self._labels.get(key)
        if entry is None:
            label = pyglet.text.Label(
                text, font_name=font or "sans-serif", font_size=size, x=px, y=py, color=tuple(color),
                anchor_x=anchor_x, anchor_y=anchor_y, batch=self.batch, group=self._text_group(space, order),
            )
        else:
            label = entry[0]
            if (label.x, label.y) != (px, py):
                label.position = (px, py, 0)
        self._labels[key] = (label, self._frame + 1)

    def measure_text(self, text: str, font_size: int, font=None) -> tuple[int, int]:
        size = max(1, round(font_size * self.scale_factor))
        key = (text, font, size)
        result = self._measure_cache.get(key)
        if result is None:
            label = pyglet.text.Label(text, font_name=font or "sans-serif", font_size=size)
            # The key identifies physical glyph size. Keep those physical
            # metrics so a later viewport scale cannot reuse old logical units.
            result = (label.content_width, label.content_height)
            label.delete()
            self._measure_cache[key] = result
        return tuple(int(round(dimension / self.scale_factor)) for dimension in result)

    def load_font(self, name: str, path: str | None = None) -> str:
        if path is not None:
            pyglet.font.add_file(path)
        return name

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def load_sound(self, path: str) -> Any:
        return pyglet.media.load(path, streaming=False)

    def play_sound(self, handle: Any, volume: float = 1.0, pitch: float = 1.0) -> int:
        player = pyglet.media.Player()
        player.volume = volume
        player.pitch = pitch
        player.queue(handle)
        player.play()
        player_id = self._track_player(player)
        self._sound_players.add(player_id)
        return player_id

    def load_music(self, path: str) -> Any:
        return pyglet.media.load(path, streaming=True)

    def play_music(self, handle: Any, *, loop: bool = True, volume: float = 1.0) -> int:
        player = pyglet.media.Player()
        player.queue(handle)
        player.loop = loop
        player.volume = volume
        player.play()
        return self._track_player(player)

    def _track_player(self, player: Any) -> int:
        player_id = self._next_player_id
        self._next_player_id += 1
        self._players[player_id] = player
        return player_id

    def set_player_volume(self, player_id: int, volume: float) -> None:
        player = self._players.get(player_id)
        if player is not None:
            player.volume = volume

    def is_player_playing(self, player_id: int) -> bool:
        player = self._players.get(player_id)
        return player is not None and player.source is not None

    def stop_sounds(self) -> None:
        for player_id in list(self._sound_players):
            self.stop_player(player_id)

    def stop_player(self, player_id: int) -> None:
        player = self._players.pop(player_id, None)
        self._sound_players.discard(player_id)
        if player is None:
            return
        # A player whose track ran out was already paused and released by
        # pyglet (Player.next_source).  Once pyglet's atexit hook has deleted
        # the audio driver, the OpenAL source under a still-playing player is
        # gone and pause() would call alSourcePause(None) — so pause only a
        # playing player on a live driver.  delete() is idempotent in pyglet.
        if player.playing and pyglet.media.get_audio_driver() is not None:
            player.pause()
        player.delete()


def _image_data(pil_image: Any) -> Any:
    return pyglet.image.ImageData(pil_image.width, pil_image.height, "RGBA", pil_image.tobytes(), pitch=-pil_image.width * 4)


def _extruded_image(image: Any) -> Any:
    """Duplicate the outer pixel ring so filtered atlas samples stay in-image."""
    width, height = image.width, image.height
    raw = image.get_image_data().get_bytes("RGBA", width * 4)
    stride = width * 4
    rows = [raw[start:start + 4] + raw[start:start + stride] + raw[start + stride - 4:start + stride]
            for start in range(0, len(raw), stride)]
    return pyglet.image.ImageData(width + 2, height + 2, "RGBA", rows[0] + b"".join(rows) + rows[-1], pitch=(width + 2) * 4)


def _group_order(space: Space, order: int) -> int:
    return (_SCREEN_ORDER_BASE if space == "screen" else 0) + 2 * order


class _ViewGroup(pyglet.graphics.Group):
    """Sets the view matrix for one (space, order) band and enables blending."""

    def __init__(self, backend: PygletBackend, space: Space, order: int) -> None:
        super().__init__(order=order)
        self._backend = backend
        self._space = space

    def set_state(self) -> None:
        backend = self._backend
        backend._apply_view(backend._world_view if self._space == "world" else backend._screen_view)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def unset_state(self) -> None:
        glDisable(GL_BLEND)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ViewGroup) and other._order == self._order and other._space == self._space

    def __hash__(self) -> int:
        return hash((_ViewGroup, self._order, self._space))


class _TextGroup(pyglet.graphics.Group):
    """Labels are positioned in physical pixels: they draw under the identity view."""

    def __init__(self, backend: PygletBackend, order: int) -> None:
        super().__init__(order=order)
        self._backend = backend

    def set_state(self) -> None:
        self._backend._apply_view(self._backend._identity)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _TextGroup) and other._order == self._order

    def __hash__(self) -> int:
        return hash((_TextGroup, self._order))


class _ShaderChild(pyglet.graphics.ShaderGroup):
    def __init__(self, program: Any, parent: Any) -> None:
        super().__init__(program, order=0, parent=parent)


class _ImageChild(pyglet.graphics.Group):
    def __init__(self, parent: Any) -> None:
        super().__init__(order=1, parent=parent)
