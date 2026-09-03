"""Mock backend: records every operation for headless tests.

Tests inspect ``mock.sprites``, ``mock.rects``, ``mock.circles``,
``mock.lines``, ``mock.polygons``, ``mock.texts``, ``mock.images``,
``mock.camera``, ``mock.sounds_played``, ``mock.frame_count`` and feed
input with ``inject_key`` / ``inject_click`` / ``inject_mouse_move`` /
``inject_scroll`` / ``inject_drag``.  Coordinates are recorded as given
(logical space, no flip, no scaling).
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from saga2d.backends.base import Color, Event, KeyEvent, MouseEvent, Space, WindowEvent


class MockBackend:
    def __init__(self, logical_width: int = 1920, logical_height: int = 1080) -> None:
        self.logical_width = logical_width
        self.logical_height = logical_height
        self.scale_factor: float = 1.0

        self.sprites: dict[str, dict[str, Any]] = {}
        self.texts: list[dict[str, Any]] = []
        self.rects: list[dict[str, Any]] = []
        self.circles: list[dict[str, Any]] = []
        self.lines: list[dict[str, Any]] = []
        self.polygons: list[dict[str, Any]] = []
        self.images: list[dict[str, Any]] = []
        self.fonts: dict[str, str | None] = {}
        self.camera: tuple[float, float, float] = (0.0, 0.0, 1.0)
        self.clear_color: Color | None = None
        self.frame_count: int = 0
        self.is_running: bool = True

        self.sounds_played: list[dict[str, Any]] = []
        self.music_playing: str | None = None
        self.music_volume: float = 1.0
        self._music_players: dict[str, dict[str, Any]] = {}

        self._pending_events: list[Event] = []
        self._next_id: int = 0
        self._loaded_images: dict[str, str] = {}
        self._loaded_sounds: dict[str, str] = {}
        self._loaded_music: dict[str, str] = {}
        self._default_image_size: tuple[int, int] = (64, 64)
        self._image_sizes: dict[str, tuple[int, int]] = {}

    def _make_id(self, prefix: str) -> str:
        handle = f"{prefix}_{self._next_id}"
        self._next_id += 1
        return handle

    # -- Lifecycle -----------------------------------------------------------

    def create_window(self, width: int, height: int, title: str, fullscreen: bool, visible: bool = True) -> None:
        self.logical_width = width
        self.logical_height = height

    def begin_frame(self, clear_color: Color | None = None) -> None:
        self.clear_color = clear_color
        self.texts.clear()
        self.rects.clear()
        self.circles.clear()
        self.lines.clear()
        self.polygons.clear()
        self.images.clear()

    def end_frame(self) -> None:
        self.frame_count += 1

    def poll_events(self) -> list[Event]:
        events = self._pending_events.copy()
        self._pending_events.clear()
        return events

    def get_dt(self) -> float:
        return 1.0 / 60.0

    def quit(self) -> None:
        self.is_running = False

    def capture_frame(self) -> Image.Image:
        return Image.new("RGBA", (self.logical_width, self.logical_height), (0, 0, 0, 255))

    def set_camera(self, x: float, y: float, zoom: float) -> None:
        self.camera = (x, y, zoom)

    # -- Images --------------------------------------------------------------

    def load_image(self, path: str) -> str:
        if path not in self._loaded_images:
            self._loaded_images[path] = self._make_id("img")
        return self._loaded_images[path]

    def load_image_from_pil(self, pil_image: Image.Image) -> str:
        handle = self._make_id("pil")
        self._image_sizes[handle] = pil_image.size
        return handle

    def get_image_size(self, image_handle: str) -> tuple[int, int]:
        return self._image_sizes.get(image_handle, self._default_image_size)

    def set_image_size(self, image_handle: str, width: int, height: int) -> None:
        """Test helper: control what :meth:`get_image_size` reports."""
        self._image_sizes[image_handle] = (width, height)

    # -- Retained sprites ----------------------------------------------------

    def create_sprite(self, image_handle: str, order: int, space: Space) -> str:
        sid = self._make_id("sprite")
        self.sprites[sid] = {
            "image": image_handle, "x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0,
            "opacity": 255, "visible": True, "tint": (1.0, 1.0, 1.0), "rotation": 0.0,
            "order": order, "space": space,
        }
        return sid

    def update_sprite(
        self, sprite_id: str, x: float, y: float, width: float, height: float, *,
        image: str | None = None, opacity: int = 255, visible: bool = True,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0), rotation: float = 0.0,
    ) -> None:
        s = self.sprites[sprite_id]
        s.update(x=x, y=y, width=width, height=height, opacity=opacity, visible=visible, tint=tint, rotation=rotation)
        if image is not None:
            s["image"] = image

    def set_sprite_order(self, sprite_id: str, order: int) -> None:
        self.sprites[sprite_id]["order"] = order

    def remove_sprite(self, sprite_id: str) -> None:
        del self.sprites[sprite_id]

    # -- Immediate-mode drawing ----------------------------------------------

    def draw_rect(self, x, y, width, height, color, *, space: Space = "screen", order: int = 0) -> None:
        self.rects.append({"x": x, "y": y, "width": width, "height": height, "color": color, "space": space, "order": order})

    def draw_circle(self, x, y, radius, color, *, space: Space = "screen", order: int = 0) -> None:
        self.circles.append({"x": x, "y": y, "radius": radius, "color": color, "space": space, "order": order})

    def draw_line(self, x1, y1, x2, y2, color, width=1.0, *, space: Space = "screen", order: int = 0) -> None:
        self.lines.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "width": width, "color": color, "space": space, "order": order})

    def draw_polygon(self, points, color, *, space: Space = "screen", order: int = 0) -> None:
        self.polygons.append({"points": list(points), "color": color, "space": space, "order": order})

    def draw_image(self, image_handle, x, y, width, height, *, opacity=1.0, space: Space = "screen", order: int = 0) -> None:
        self.images.append({"image": image_handle, "x": x, "y": y, "width": width, "height": height, "opacity": opacity, "space": space, "order": order})

    def draw_text(self, text, x, y, font_size, color, *, font=None, anchor_x="left", anchor_y="baseline", space: Space = "screen", order: int = 0) -> None:
        self.texts.append({"text": text, "x": x, "y": y, "font_size": font_size, "color": color, "font": font, "anchor_x": anchor_x, "anchor_y": anchor_y, "space": space, "order": order})

    def measure_text(self, text: str, font_size: int, font=None) -> tuple[int, int]:
        return (int(len(text) * font_size * 0.6), int(font_size * 1.2))

    def load_font(self, name: str, path: str | None = None) -> str:
        self.fonts[name] = path
        return name

    # -- Audio ---------------------------------------------------------------

    def load_sound(self, path: str) -> str:
        if path not in self._loaded_sounds:
            self._loaded_sounds[path] = self._make_id("sound")
        return self._loaded_sounds[path]

    def play_sound(self, handle: str, volume: float = 1.0) -> None:
        self.sounds_played.append({"handle": handle, "volume": volume})

    def load_music(self, path: str) -> str:
        if path not in self._loaded_music:
            self._loaded_music[path] = self._make_id("music")
        return self._loaded_music[path]

    def play_music(self, handle: str, *, loop: bool = True, volume: float = 1.0) -> str:
        pid = self._make_id("player")
        self._music_players[pid] = {"handle": handle, "volume": volume, "loop": loop}
        self.music_playing = handle
        self.music_volume = volume
        return pid

    def set_player_volume(self, player_id: str, volume: float) -> None:
        self._music_players[player_id]["volume"] = volume
        self.music_volume = volume

    def stop_player(self, player_id: str) -> None:
        player = self._music_players.pop(player_id)
        if self.music_playing == player["handle"]:
            self.music_playing = None
            self.music_volume = 1.0

    # -- Test helpers: event injection ---------------------------------------

    def inject_key(self, key: str, type: str = "key_press", *, shift=False, ctrl=False, alt=False, meta=False) -> None:
        self._pending_events.append(KeyEvent(type=type, key=key, shift=shift, ctrl=ctrl, alt=alt, meta=meta))

    def inject_click(self, x: int, y: int, button: str = "left") -> None:
        self._pending_events.append(MouseEvent(type="click", x=x, y=y, button=button))

    def inject_release(self, x: int, y: int, button: str = "left") -> None:
        self._pending_events.append(MouseEvent(type="release", x=x, y=y, button=button))

    def inject_mouse_move(self, x: int, y: int) -> None:
        self._pending_events.append(MouseEvent(type="move", x=x, y=y))

    def inject_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._pending_events.append(MouseEvent(type="scroll", x=x, y=y, dx=dx, dy=dy))

    def inject_drag(self, x: int, y: int, dx: int, dy: int, button: str = "left") -> None:
        self._pending_events.append(MouseEvent(type="drag", x=x, y=y, button=button, dx=dx, dy=dy))

    def inject_window_event(self, type: str) -> None:
        self._pending_events.append(WindowEvent(type=type))

    def inject_event(self, event: Event) -> None:
        self._pending_events.append(event)
