"""Backend protocol, event types, and opaque handle type aliases.

This module defines the interface that all backends must satisfy (via structural
subtyping / Protocol), the event dataclasses dispatched through the framework,
and opaque handle types that the framework passes around without inspecting.

The Backend protocol starts minimal (Stage 0: lifecycle + events + quit) and
grows as later stages add rendering, audio, and asset operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from PIL import Image as PILImage


# ---------------------------------------------------------------------------
# Opaque handle type aliases
# ---------------------------------------------------------------------------
# These are intentionally Any.  The mock backend uses string IDs; the pyglet
# backend uses real pyglet objects.  Framework code passes handles around
# opaquely and never inspects their internals.

ImageHandle = Any
"""Opaque reference to a loaded image.

Mock: ``"img_0"``  /  Pyglet: ``pyglet.image.AbstractImage``
"""

SoundHandle = Any
"""Opaque reference to a loaded audio source (sound effect or music).

Mock: ``"sound_path"``  /  Pyglet: ``pyglet.media.Source``
"""

FontHandle = Any
"""Opaque reference to a loaded font.

Mock: ``"font_name"`` or ``(name, path)``  /  Pyglet: font name or path
"""

MusicPlayerId = Any
"""Opaque reference to a music player (from :meth:`Backend.play_music`).

Used for volume control and stop. Mock: string id  /  Pyglet: Player instance.
"""


# ---------------------------------------------------------------------------
# Event dataclasses  (frozen — events are immutable value objects)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyEvent:
    """Keyboard press or release.

    Attributes:
        type: ``"key_press"`` or ``"key_release"``.
        key:  Backend-agnostic string name, e.g. ``"space"``, ``"a"``,
              ``"escape"``, ``"return"``, ``"up"``, ``"down"``.
    """

    type: str  # "key_press" | "key_release"
    key: str


@dataclass(frozen=True)
class MouseEvent:
    """Mouse click, release, movement, drag, or scroll.

    Coordinates are in *logical* space (the framework's fixed coordinate
    system, e.g. 0..1920, 0..1080).  The backend converts from physical
    pixels before creating the event.

    Attributes:
        type:   ``"click"`` | ``"release"`` | ``"move"`` | ``"drag"`` | ``"scroll"``
        x:      Logical x coordinate.
        y:      Logical y coordinate.
        button: ``"left"`` | ``"right"`` | ``"middle"`` | ``None``
                (``None`` for move / scroll events).
        dx:     Horizontal scroll delta (scroll events) or drag delta. 0 by default.
        dy:     Vertical scroll delta (scroll events) or drag delta. 0 by default.
    """

    type: str  # "click" | "release" | "move" | "drag" | "scroll"
    x: int
    y: int
    button: str | None = None
    dx: int = 0
    dy: int = 0


@dataclass(frozen=True)
class WindowEvent:
    """Window lifecycle events.

    Attributes:
        type: ``"close"`` | ``"resize"``
    """

    type: str  # "close" | "resize"


#: Union of all event types dispatched by a backend.
Event = KeyEvent | MouseEvent | WindowEvent


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


class Backend(Protocol):
    """Interface that every backend must satisfy (structural subtyping).

    Backends are never subclassed from this class — they simply implement the
    same method signatures.  This keeps the mock backend and the pyglet
    backend fully decoupled.

    The protocol is shown in its *full planned* form.  Stage 0 tests only
    exercise the lifecycle / event / quit subset; later stages exercise
    rendering, audio, and asset methods as they are implemented.
    """

    # -- Lifecycle -----------------------------------------------------------

    def create_window(
        self,
        width: int,
        height: int,
        title: str,
        fullscreen: bool,
        visible: bool = True,
    ) -> None:
        """Create (or reconfigure) the application window.

        *width* and *height* are the logical resolution.  The backend may
        open a physical window at a different size and compute the scale
        factor accordingly.  *visible* controls whether the window is
        initially visible (default ``True``).
        """
        ...

    def begin_frame(
        self,
        clear_color: tuple[int, ...] | None = None,
    ) -> None:
        """Begin a new frame.

        Called once per tick before any draw calls.  GPU backends use this to
        clear the backbuffer; the mock backend resets per-frame state.

        If *clear_color* is provided as (R,G,B) or (R,G,B,A) (0–255), the
        screen is cleared with that color before drawing.
        """
        ...

    def end_frame(self) -> None:
        """End the current frame.

        GPU backends submit the batch and flip/present.  The mock backend
        increments its frame counter.
        """
        ...

    def poll_events(self) -> list[Event]:
        """Drain and return all pending input / window events.

        Returns a (possibly empty) list of :class:`Event` objects.  Events
        use logical coordinates — the backend converts physical pixels to
        the framework's coordinate space before returning them.
        """
        ...

    def get_dt(self) -> float:
        """Return seconds elapsed since the last frame (delta time).

        Used by ``Game.run()`` to feed real wall-clock dt into the loop.
        ``Game.tick(dt=...)`` bypasses this by accepting an explicit value.
        """
        ...

    def quit(self) -> None:
        """Tear down the window and release backend resources."""
        ...

    # -- Image / sprite rendering -------------------------------------------

    def load_image(self, path: str) -> ImageHandle:
        """Load an image from *path* and return an opaque handle."""
        ...

    def load_image_from_pil(self, pil_image: "PILImage.Image") -> ImageHandle:
        """Create an image handle from a PIL Image object.

        Used by ColorSwap to load recolored images. The image must be RGBA.
        """
        ...

    def set_cursor(
        self,
        image_handle: ImageHandle | None,
        hotspot_x: int = 0,
        hotspot_y: int = 0,
    ) -> None:
        """Set a custom cursor image. None restores system default."""
        ...

    def set_cursor_visible(self, visible: bool) -> None:
        """Show or hide the mouse cursor."""
        ...

    def create_solid_color_image(
        self,
        r: int,
        g: int,
        b: int,
        a: int,
        width: int,
        height: int,
    ) -> ImageHandle:
        """Create a solid-color image of the given size and return a handle.

        Useful for programmatic backgrounds and overlays that don't need
        a PNG file on disk.
        """
        ...

    def create_sprite(
        self,
        image_handle: ImageHandle,
        layer_order: int,
    ) -> Any:
        """Create a persistent sprite in the render batch.

        *layer_order* determines draw order (lower = behind).
        Returns an opaque sprite id that the framework uses to update or
        remove the sprite later.
        """
        ...

    def update_sprite(
        self,
        sprite_id: Any,
        x: int,
        y: int,
        *,
        image: ImageHandle | None = None,
        opacity: int = 255,
        visible: bool = True,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
    ) -> None:
        """Update a sprite's position and visual properties.

        Called every frame for each live sprite.  Coordinates are *physical*
        (the framework converts logical -> physical before calling).
        """
        ...

    def remove_sprite(self, sprite_id: Any) -> None:
        """Remove a sprite from the render batch."""
        ...

    def get_image_size(self, image_handle: ImageHandle) -> tuple[int, int]:
        """Return ``(width, height)`` of a loaded image.

        Used by the Sprite class to compute anchor offsets (e.g.
        BOTTOM_CENTER needs the image height to offset upward).
        """
        ...

    def set_sprite_order(self, sprite_id: Any, order: int) -> None:
        """Update the draw order of an existing sprite.

        Called when a sprite's y-position changes (y-sorting) so that
        sprites further down the screen are drawn in front.  *order*
        combines the render layer and y-position into a single integer.
        """
        ...

    def capture_frame(self) -> "PILImage.Image":
        """Return a PIL Image of the current framebuffer contents.

        The returned image has the same dimensions as the window
        (logical or physical, backend-dependent) and is in RGBA format.
        """
        ...

    # -- Rect and text rendering ---------------------------------------------

    def set_ui_layer(self, layer: int) -> None:
        """Set the current UI draw layer for subsequent draw_rect/draw_text calls.

        Higher layers render on top of lower layers.  The game loop calls this
        before each scene's draw phase so overlay panels correctly occlude
        content from scenes below.  Layer 0 is the default.
        """
        ...

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
        """Draw a filled RGBA rectangle. Per-frame call (cleared each begin_frame)."""
        ...

    def load_font(self, name: str, path: str | None = None) -> FontHandle:
        """Load a font from *path* and register it as *name*.

        When *path* is None, use the system font with the given *name*.
        Returns an opaque handle for use with draw_text.
        """
        ...

    def draw_text(
        self,
        text: str,
        x: int,
        y: int,
        font_size: int,
        color: tuple[int, int, int, int],
        *,
        font: FontHandle | None = None,
        anchor_x: str = "left",
        anchor_y: str = "baseline",
    ) -> None:
        """Draw *text* at ``(x, y)``.

        *font_size* is the logical size. *font* is a handle from load_font,
        or None for the default font. *anchor_x* and *anchor_y* control
        alignment (e.g. "center", "left", "right", "baseline", "top", "bottom").
        Per-frame call (cleared each begin_frame).
        """
        ...

    def draw_image(
        self,
        image_handle: ImageHandle,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        opacity: float = 1.0,
    ) -> None:
        """Draw an image at ``(x, y)`` scaled to ``(width, height)``.

        *image_handle* is an opaque handle from :meth:`load_image`.
        *opacity* ranges from 0.0 (fully transparent) to 1.0 (fully opaque).
        Per-frame call (cleared each begin_frame).

        This is used by UI components (e.g. ``Image`` widget) to draw
        images in screen space without creating persistent sprites.
        """
        ...

    # -- Audio --------------------------------------------------------------

    def load_sound(self, path: str) -> SoundHandle:
        """Load a short sound effect from *path* (non-streaming)."""
        ...

    def play_sound(self, handle: SoundHandle, volume: float = 1.0) -> None:
        """Play a previously loaded sound effect."""
        ...

    def load_music(self, path: str) -> SoundHandle:
        """Load a music track from *path* (streaming)."""
        ...

    def play_music(
        self,
        handle: SoundHandle,
        *,
        loop: bool = True,
        volume: float = 1.0,
    ) -> MusicPlayerId:
        """Start playing a music track.

        Returns an opaque player id for volume / stop control.
        """
        ...

    def set_player_volume(self, player_id: MusicPlayerId, volume: float) -> None:
        """Set the volume on a currently-playing music player."""
        ...

    def stop_player(self, player_id: MusicPlayerId) -> None:
        """Stop and dispose of a music player."""
        ...
