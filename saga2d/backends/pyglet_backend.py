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
"""

from __future__ import annotations

from typing import Any

import pyglet
import pyglet.graphics
import pyglet.window  # must precede pyglet.gl: it initialises the display
from pyglet.gl import GL_BLEND, GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA, glBlendFunc, glDisable, glEnable

from saga2d.backends.base import Color, Event, KeyEvent, MouseEvent, Space, WindowEvent

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
        self._frame_images: list[Any] = []
        self._labels: dict[tuple[Any, ...], tuple[Any, int]] = {}
        self._label_uses: dict[tuple[Any, ...], int] = {}
        self._frame = 0
        self._measure_cache: dict[tuple[str, str | None, int], tuple[int, int]] = {}
        self._atlas: Any = None
        self._identity: Any = None
        self._screen_view: Any = None
        self._world_view: Any = None

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def _compute_viewport(self, physical_w: int, physical_h: int) -> None:
        from pyglet.math import Mat4, Vec3

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
                width=width, height=height, caption=title, fullscreen=fullscreen,
                vsync=True, visible=visible, config=config,
            )
        except pyglet.window.NoSuchConfigException:
            self.window = pyglet.window.Window(
                width=width, height=height, caption=title, fullscreen=fullscreen, vsync=True, visible=visible,
            )
        self.batch = pyglet.graphics.Batch()
        self._identity = Mat4()
        self._atlas = pyglet.image.atlas.TextureBin(2048, 2048)
        self._shape_program = pyglet.gl.current_context.create_program(
            (_SHAPE_VERTEX_SRC, "vertex"), (_SHAPE_FRAGMENT_SRC, "fragment"),
        )
        self._compute_viewport(self.window.width, self.window.height)
        self._register_handlers()

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

        @window.event
        def on_mouse_press(x: int, y: int, button: int, modifiers: int) -> bool:
            lx, ly = self._to_logical(x, y)
            queue.append(MouseEvent("click", lx, ly, _button_to_name(button)))
            return True

        @window.event
        def on_mouse_release(x: int, y: int, button: int, modifiers: int) -> bool:
            lx, ly = self._to_logical(x, y)
            queue.append(MouseEvent("release", lx, ly, _button_to_name(button)))
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
            queue.append(MouseEvent("drag", lx, ly, _button_to_name(buttons), dx=int(dx / s), dy=int(-dy / s)))
            return True

        @window.event
        def on_mouse_scroll(x: int, y: int, scroll_x: float, scroll_y: float) -> bool:
            lx, ly = self._to_logical(x, y)
            queue.append(MouseEvent("scroll", lx, ly, dx=int(scroll_x), dy=int(scroll_y)))
            return True

        @window.event
        def on_close() -> bool:
            queue.append(WindowEvent("close"))
            return pyglet.event.EVENT_HANDLED

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
        for sprite in self._frame_images:
            sprite.delete()
        self._frame_images.clear()
        self._label_uses.clear()

    def end_frame(self) -> None:
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
        self.batch.draw()
        self.window.flip()

    def poll_events(self) -> list[Event]:
        self.window.dispatch_events()
        events = self._event_queue.copy()
        self._event_queue.clear()
        return events

    def get_dt(self) -> float:
        return pyglet.clock.tick()

    def quit(self) -> None:
        if self.window is not None:
            self.window.close()
            self.window = None

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
            group = pyglet.graphics.Group(order=_group_order(space, order) + 1)
            self._text_groups[key] = group
        return group

    # ------------------------------------------------------------------
    # Images and sprites
    # ------------------------------------------------------------------

    def _atlas_add(self, image_data: Any) -> Any:
        if image_data.width > 1024 or image_data.height > 1024:
            region = image_data.get_texture()
        else:
            region = self._atlas.add(image_data, border=1)
        region.anchor_x = region.width / 2
        region.anchor_y = region.height / 2
        return region

    def load_image(self, path: str) -> Any:
        return self._atlas_add(pyglet.image.load(path))

    def load_image_from_pil(self, pil_image: Any) -> Any:
        data = pyglet.image.ImageData(pil_image.width, pil_image.height, "RGBA", pil_image.tobytes(), pitch=-pil_image.width * 4)
        return self._atlas_add(data)

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
        sprite.opacity = opacity
        sprite.visible = visible
        sprite.color = (int(tint[0] * 255), int(tint[1] * 255), int(tint[2] * 255))

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
        sprite = pyglet.sprite.Sprite(
            image_handle, x=x + width / 2, y=self._flip(y + height / 2, space),
            batch=self.batch, group=_ImageChild(self._view_group(space, order)),
        )
        sprite.scale_x = width / image_handle.width
        sprite.scale_y = height / image_handle.height
        sprite.opacity = int(opacity * 255)
        self._frame_images.append(sprite)

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
            result = (
                int(round(label.content_width / self.scale_factor)),
                int(round(label.content_height / self.scale_factor)),
            )
            label.delete()
            self._measure_cache[key] = result
        return result

    def load_font(self, name: str, path: str | None = None) -> str:
        if path is not None:
            pyglet.font.add_file(path)
        return name

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def load_sound(self, path: str) -> Any:
        return pyglet.media.load(path, streaming=False)

    def play_sound(self, handle: Any, volume: float = 1.0) -> None:
        player = handle.play()
        player.volume = volume

    def load_music(self, path: str) -> Any:
        return pyglet.media.load(path, streaming=True)

    def play_music(self, handle: Any, *, loop: bool = True, volume: float = 1.0) -> Any:
        player = pyglet.media.Player()
        player.queue(handle)
        player.loop = loop
        player.volume = volume
        player.play()
        return player

    def set_player_volume(self, player_id: Any, volume: float) -> None:
        player_id.volume = volume

    def stop_player(self, player_id: Any) -> None:
        player_id.delete()


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
        backend.window.view = backend._world_view if self._space == "world" else backend._screen_view
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def unset_state(self) -> None:
        glDisable(GL_BLEND)
        self._backend.window.view = self._backend._identity

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ViewGroup) and other._order == self._order and other._space == self._space

    def __hash__(self) -> int:
        return hash((_ViewGroup, self._order, self._space))


class _ShaderChild(pyglet.graphics.ShaderGroup):
    def __init__(self, program: Any, parent: Any) -> None:
        super().__init__(program, order=0, parent=parent)


class _ImageChild(pyglet.graphics.Group):
    def __init__(self, parent: Any) -> None:
        super().__init__(order=1, parent=parent)
