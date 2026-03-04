"""Mock backend that records all operations for headless testing.

``MockBackend`` satisfies the :class:`~easygame.backends.base.Backend`
protocol without opening a window, rendering pixels, or playing audio.
It serves two purposes:

1. **Assertions** — tests inspect ``mock.sprites``, ``mock.texts``,
   ``mock.rects``, ``mock.images``, ``mock.fonts``, ``mock.sounds_played``,
   ``mock.frame_count``, etc.
2. **Simulation** — tests call ``mock.inject_key("space")``,
   ``mock.inject_click(400, 300)`` to feed events into the framework.

All coordinates stay in *logical* space (no y-flip, no scaling, no offset).
``scale_factor`` is always 1.0.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from saga2d.backends.base import (
    Event,
    KeyEvent,
    MouseEvent,
    WindowEvent,
)


class MockBackend:
    """Backend that records all operations for testing.

    Does not inherit from or register with :class:`Backend` — it satisfies
    the protocol via structural subtyping (duck typing).
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        logical_width: int = 1920,
        logical_height: int = 1080,
    ) -> None:
        self.logical_width = logical_width
        self.logical_height = logical_height
        self.scale_factor: float = 1.0  # no physical scaling in tests

        # === Recorded state (what tests assert on) =====================

        #: Registered sprites.  ``sprite_id -> {image, x, y, opacity,
        #: visible, layer}``.
        self.sprites: dict[str, dict[str, Any]] = {}

        #: ``draw_text`` calls accumulated during the **current** frame.
        #: Cleared on every :meth:`begin_frame`.
        self.texts: list[dict[str, Any]] = []

        #: ``draw_rect`` calls accumulated during the **current** frame.
        #: Cleared on every :meth:`begin_frame`.
        self.rects: list[dict[str, Any]] = []

        #: ``draw_image`` calls accumulated during the **current** frame.
        #: Cleared on every :meth:`begin_frame`.
        self.images: list[dict[str, Any]] = []

        #: ``load_font`` registrations. ``name -> path`` (path may be None for system fonts).
        self.fonts: dict[str, str | None] = {}

        #: Number of completed frames (incremented by :meth:`end_frame`).
        self.frame_count: int = 0

        #: ``True`` until :meth:`quit` is called.
        self.is_running: bool = True

        # === Audio recording ===========================================

        #: Every ``play_sound`` call appended here (cumulative, never
        #: cleared automatically).  Each entry is ``{"handle": str,
        #: "volume": float}``.
        self.sounds_played: list[dict[str, Any]] = []

        #: Handle string of the music track currently playing, or
        #: ``None`` if nothing is playing.
        self.music_playing: str | None = None

        #: Volume of the current music player (last value set via
        #: :meth:`set_player_volume` on the active player).
        self.music_volume: float = 1.0

        # === Music player tracking =====================================

        #: ``player_id -> {handle, volume, loop, playing}``
        self._music_players: dict[str, dict[str, Any]] = {}

        # === Event injection (how tests simulate input) ================

        self._pending_events: list[Event] = []

        # === Handle bookkeeping ========================================

        self._next_id: int = 0
        self._loaded_images: dict[str, str] = {}  # path -> handle
        self._loaded_sounds: dict[str, str] = {}  # path -> handle
        self._loaded_music: dict[str, str] = {}  # path -> handle

        # === Image size tracking ============================================

        #: Default size returned by :meth:`get_image_size` when no override
        #: has been set via :meth:`set_image_size`.
        self._default_image_size: tuple[int, int] = (64, 64)

        #: Per-handle overrides.  ``image_handle -> (width, height)``.
        self._image_sizes: dict[str, tuple[int, int]] = {}

        # === Cursor tracking ===========================================
        self.cursor_image: str | None = None
        self.cursor_hotspot: tuple[int, int] = (0, 0)
        self.cursor_visible: bool = True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_id(self, prefix: str) -> str:
        """Return a unique string id like ``"sprite_7"``."""
        handle = f"{prefix}_{self._next_id}"
        self._next_id += 1
        return handle

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
        """No-op — there is no window in the mock."""
        self.logical_width = width
        self.logical_height = height

    def begin_frame(
        self,
        clear_color: tuple[int, ...] | None = None,
    ) -> None:
        """Reset per-frame recorded state."""
        self.clear_color = clear_color  # for tests
        self.texts.clear()
        self.rects.clear()
        self.images.clear()

    def end_frame(self) -> None:
        """Increment the frame counter."""
        self.frame_count += 1

    def poll_events(self) -> list[Event]:
        """Drain and return all injected events."""
        events = self._pending_events.copy()
        self._pending_events.clear()
        return events

    def get_dt(self) -> float:
        """Return a fixed 16ms delta (≈60 fps).

        In tests the caller usually passes an explicit ``dt`` via
        ``Game.tick(dt=...)``, so this is rarely used.
        """
        return 1.0 / 60.0

    def quit(self) -> None:
        """Mark the backend as no longer running."""
        self.is_running = False

    # ==================================================================
    # Backend protocol — image / sprite rendering
    # ==================================================================

    def load_image(self, path: str) -> str:
        """Return a cached string handle like ``"img_3"``."""
        if path not in self._loaded_images:
            self._loaded_images[path] = self._make_id("img")
        return self._loaded_images[path]

    def load_image_from_pil(self, pil_image: Image.Image) -> str:
        """Create an image handle from a PIL Image. Stores dimensions for get_image_size."""
        handle = self._make_id("pil_img")
        self._image_sizes[handle] = (pil_image.width, pil_image.height)
        return handle

    def create_solid_color_image(
        self,
        r: int,
        g: int,
        b: int,
        a: int,
        width: int,
        height: int,
    ) -> str:
        """Return a mock image handle for a solid-color image."""
        handle = self._make_id("solid")
        self._image_sizes[handle] = (width, height)
        return handle

    def create_sprite(self, image_handle: str, layer_order: int) -> str:
        """Register a new sprite and return its id."""
        sid = self._make_id("sprite")
        self.sprites[sid] = {
            "image": image_handle,
            "x": 0,
            "y": 0,
            "opacity": 255,
            "visible": True,
            "layer": layer_order,
            "tint": (1.0, 1.0, 1.0),
        }
        return sid

    def update_sprite(
        self,
        sprite_id: str,
        x: int,
        y: int,
        *,
        image: str | None = None,
        opacity: int = 255,
        visible: bool = True,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ) -> None:
        """Record updated position / visual properties."""
        s = self.sprites[sprite_id]
        s["x"] = x
        s["y"] = y
        s["opacity"] = opacity
        s["visible"] = visible
        s["tint"] = tint
        if image is not None:
            s["image"] = image

    def remove_sprite(self, sprite_id: str) -> None:
        """Remove a sprite from the recorded state."""
        del self.sprites[sprite_id]

    def get_image_size(self, image_handle: str) -> tuple[int, int]:
        """Return ``(width, height)`` for a loaded image.

        Returns the size set via :meth:`set_image_size`, or the default
        ``(64, 64)`` if no override exists.
        """
        return self._image_sizes.get(image_handle, self._default_image_size)

    def set_sprite_order(self, sprite_id: str, order: int) -> None:
        """Update the draw order of an existing sprite."""
        self.sprites[sprite_id]["layer"] = order

    def capture_frame(self) -> Image.Image:
        """Return a blank RGBA image of the window dimensions."""
        return Image.new(
            "RGBA",
            (self.logical_width, self.logical_height),
            (0, 0, 0, 0),
        )

    # ==================================================================
    # Backend protocol — rect and text rendering
    # ==================================================================

    def set_ui_layer(self, layer: int) -> None:
        """No-op in mock — layer ordering doesn't affect recorded output."""
        pass

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
        """Record a rect draw call for the current frame."""
        self.rects.append(
            {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "color": color,
                "opacity": opacity,
            }
        )

    def load_font(self, name: str, path: str | None = None) -> str:
        """Register a font and return a handle like ``"font_name"``."""
        self.fonts[name] = path
        return f"font_{name}"

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
        """Record a text draw call for the current frame."""
        self.texts.append(
            {
                "text": text,
                "x": x,
                "y": y,
                "font_size": font_size,
                "color": color,
                "font": font,
                "anchor_x": anchor_x,
                "anchor_y": anchor_y,
            }
        )

    def draw_image(
        self,
        image_handle: str,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        opacity: float = 1.0,
    ) -> None:
        """Record an image draw call for the current frame."""
        self.images.append(
            {
                "image": image_handle,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "opacity": opacity,
            }
        )

    # ==================================================================
    # Backend protocol — audio
    # ==================================================================

    def load_sound(self, path: str) -> str:
        """Return a cached string handle like ``"sound_2"``."""
        if path not in self._loaded_sounds:
            self._loaded_sounds[path] = self._make_id("sound")
        return self._loaded_sounds[path]

    def play_sound(self, handle: str, volume: float = 1.0) -> None:
        """Record that a sound was played (handle and volume)."""
        self.sounds_played.append({"handle": handle, "volume": volume})

    def load_music(self, path: str) -> str:
        """Return a cached string handle like ``"music_1"``."""
        if path not in self._loaded_music:
            self._loaded_music[path] = self._make_id("music")
        return self._loaded_music[path]

    def play_music(
        self,
        handle: str,
        *,
        loop: bool = True,
        volume: float = 1.0,
    ) -> str:
        """Create a mock music player and return its id."""
        player_id = self._make_id("player")
        self._music_players[player_id] = {
            "handle": handle,
            "volume": volume,
            "loop": loop,
            "playing": True,
        }
        # Update convenience fields
        self.music_playing = handle
        self.music_volume = volume
        return player_id

    def set_player_volume(self, player_id: str, volume: float) -> None:
        """Record a volume change on a music player."""
        player = self._music_players[player_id]
        player["volume"] = volume
        # Keep the convenience field in sync with the *most recent* player
        if player["playing"]:
            self.music_volume = volume

    def stop_player(self, player_id: str) -> None:
        """Stop a music player and remove it from tracked players."""
        player = self._music_players.pop(player_id)
        player["playing"] = False
        # If we just stopped the player that was providing music_playing,
        # see if any other player is still active.
        if self.music_playing == player["handle"]:
            active = [p for p in self._music_players.values() if p["playing"]]
            if active:
                last = active[-1]
                self.music_playing = last["handle"]
                self.music_volume = last["volume"]
            else:
                self.music_playing = None
                self.music_volume = 1.0

    # ==================================================================
    # Test helpers — event injection
    # ==================================================================

    def inject_key(self, key: str, type: str = "key_press") -> None:
        """Inject a keyboard event into the pending queue.

        >>> mock.inject_key("space")
        >>> mock.inject_key("escape", type="key_release")
        """
        self._pending_events.append(KeyEvent(type=type, key=key))

    def inject_click(
        self,
        x: int,
        y: int,
        button: str = "left",
    ) -> None:
        """Inject a mouse click at logical coordinates.

        >>> mock.inject_click(400, 300)
        >>> mock.inject_click(100, 200, button="right")
        """
        self._pending_events.append(
            MouseEvent(type="click", x=x, y=y, button=button),
        )

    def inject_mouse_move(self, x: int, y: int) -> None:
        """Inject a mouse move event at logical coordinates.

        >>> mock.inject_mouse_move(960, 540)
        """
        self._pending_events.append(
            MouseEvent(type="move", x=x, y=y, button=None),
        )

    def inject_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        """Inject a mouse scroll event at logical coordinates.

        >>> mock.inject_scroll(960, 540, dx=0, dy=-3)
        """
        self._pending_events.append(
            MouseEvent(type="scroll", x=x, y=y, button=None, dx=dx, dy=dy),
        )

    def inject_drag(
        self,
        x: int,
        y: int,
        dx: int,
        dy: int,
        button: str = "left",
    ) -> None:
        """Inject a mouse drag event at logical coordinates.

        >>> mock.inject_drag(400, 300, dx=10, dy=0)
        """
        self._pending_events.append(
            MouseEvent(type="drag", x=x, y=y, button=button, dx=dx, dy=dy),
        )

    def inject_window_event(self, type: str) -> None:
        """Inject a window event (``"close"`` or ``"resize"``).

        >>> mock.inject_window_event("close")
        """
        self._pending_events.append(WindowEvent(type=type))

    def inject_event(self, event: Event) -> None:
        """Inject an arbitrary pre-built event.

        Useful when a test needs full control over event construction::

            mock.inject_event(MouseEvent(type="click", x=10, y=20,
                                         button="right"))
        """
        self._pending_events.append(event)

    def set_cursor(
        self,
        image_handle: str | None,
        hotspot_x: int = 0,
        hotspot_y: int = 0,
    ) -> None:
        """Record cursor state for test assertions."""
        self.cursor_image = image_handle
        self.cursor_hotspot = (hotspot_x, hotspot_y)

    def set_cursor_visible(self, visible: bool) -> None:
        """Record cursor visibility for test assertions."""
        self.cursor_visible = visible

    def set_image_size(
        self,
        image_handle: str,
        width: int,
        height: int,
    ) -> None:
        """Set the size returned by :meth:`get_image_size` for *image_handle*.

        Use this to control image dimensions in tests that verify anchor
        offset math::

            img = mock.load_image("knight.png")
            mock.set_image_size(img, 48, 96)
            assert mock.get_image_size(img) == (48, 96)
        """
        self._image_sizes[image_handle] = (width, height)
