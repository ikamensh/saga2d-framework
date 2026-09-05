"""Backend protocol, event types, and opaque handle type aliases.

A backend owns the window, the GPU (or a recording of draw calls, for the
mock), and audio playback.  Framework code talks to it through this
protocol only; game code never touches it.

Two coordinate spaces exist:

* ``"screen"`` — logical screen pixels, top-left origin, y-down.  UI lives
  here.
* ``"world"`` — logical world units, top-left origin, y-down, transformed
  by the camera set via :meth:`Backend.set_camera`.  Sprites default here.

Draw order is an integer ``order``: lower draws first.  Sprites are
retained (created once, updated on change); rects, circles, lines, text
and images are immediate-mode (re-issued every frame between
``begin_frame`` and ``end_frame``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from PIL import Image as PILImage

ImageHandle = Any
SoundHandle = Any
FontHandle = Any
PlayerId = Any
Space = Literal["screen", "world"]
Color = tuple[int, int, int, int]


def silent_audio(environ: Mapping[str, str] = os.environ) -> bool:
    """``SAGA2D_SILENT=1`` — or ``SAGA2D_HEADLESS=1``, since headless implies
    silent — asks backends to keep every sound off the speakers while still
    running the load/play/stop code paths."""
    return any(environ.get(name, "").strip() not in ("", "0") for name in ("SAGA2D_SILENT", "SAGA2D_HEADLESS"))


@dataclass(frozen=True)
class KeyEvent:
    """Keyboard press or release.  ``key`` is a lowercase backend-agnostic
    name: ``"a"``, ``"space"``, ``"escape"``, ``"return"``, ``"up"``…"""

    type: str  # "key_press" | "key_release"
    key: str
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    meta: bool = False


@dataclass(frozen=True)
class MouseEvent:
    """Mouse click, release, move, drag, or scroll in logical screen coords."""

    type: str  # "click" | "release" | "move" | "drag" | "scroll"
    x: int
    y: int
    button: str | None = None
    dx: float = 0.0  # drag: pointer movement; scroll: wheel lines, fractional on trackpads
    dy: float = 0.0


@dataclass(frozen=True)
class WindowEvent:
    type: str  # "close" | "resize"


Event = KeyEvent | MouseEvent | WindowEvent


class Backend(Protocol):
    """Interface every backend satisfies via structural subtyping."""

    scale_factor: float

    # -- Lifecycle -----------------------------------------------------------

    def screen_size(self) -> tuple[int, int]:
        """Size of the primary display in logical units."""
        ...

    def create_window(
        self, width: int, height: int, title: str, fullscreen: bool, visible: bool = True,
    ) -> None: ...

    def begin_frame(self, clear_color: Color | None = None) -> None: ...

    def end_frame(self) -> None: ...

    def poll_events(self) -> list[Event]: ...

    def get_dt(self) -> float: ...

    def quit(self) -> None: ...

    @property
    def fullscreen(self) -> bool: ...

    @property
    def window_size(self) -> tuple[int, int]:
        """Actual native content size, excluding decorations and backing scale."""
        ...

    @property
    def windowed_size(self) -> tuple[int, int]:
        """Actual windowed size, or remembered restoration size while fullscreen."""
        ...

    def set_fullscreen(self, fullscreen: bool) -> None:
        """Enter desktop fullscreen or restore the last actual windowed size."""
        ...

    def set_window_size(self, width: int, height: int) -> None:
        """Enter windowed mode at this content size; retain the logical canvas."""
        ...

    def capture_frame(self) -> "PILImage.Image": ...

    # -- Camera --------------------------------------------------------------

    def set_camera(self, x: float, y: float, zoom: float) -> None:
        """World-space transform: screen = (world - (x, y)) * zoom."""
        ...

    # -- Images --------------------------------------------------------------

    def load_image(self, path: str) -> ImageHandle: ...

    def load_image_from_pil(self, pil_image: "PILImage.Image") -> ImageHandle: ...

    def get_image_size(self, image_handle: ImageHandle) -> tuple[int, int]: ...

    # -- Retained sprites ----------------------------------------------------

    def create_sprite(self, image_handle: ImageHandle, order: int, space: Space) -> Any: ...

    def update_sprite(
        self,
        sprite_id: Any,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        image: ImageHandle | None = None,
        opacity: int = 255,
        visible: bool = True,
        tint: tuple[float, float, float] = (1.0, 1.0, 1.0),
        rotation: float = 0.0,
    ) -> None:
        """``(x, y)`` is the top-left corner; ``width``/``height`` the drawn
        size in logical units; ``rotation`` in degrees, clockwise, about the
        sprite's centre."""
        ...

    def set_sprite_order(self, sprite_id: Any, order: int) -> None: ...

    def remove_sprite(self, sprite_id: Any) -> None: ...

    # -- Immediate-mode drawing ----------------------------------------------

    def draw_rect(
        self, x: float, y: float, width: float, height: float, color: Color,
        *, space: Space = "screen", order: int = 0,
    ) -> None: ...

    def draw_circle(
        self, x: float, y: float, radius: float, color: Color,
        *, space: Space = "screen", order: int = 0,
    ) -> None: ...

    def draw_line(
        self, x1: float, y1: float, x2: float, y2: float, color: Color, width: float = 1.0,
        *, space: Space = "screen", order: int = 0,
    ) -> None: ...

    def draw_polygon(
        self, points: list[tuple[float, float]], color: Color,
        *, space: Space = "screen", order: int = 0,
    ) -> None:
        """Filled convex polygon (fan-triangulated from the first point)."""
        ...

    def draw_image(
        self, image_handle: ImageHandle, x: float, y: float, width: float, height: float,
        *, opacity: float = 1.0, space: Space = "screen", order: int = 0,
    ) -> None: ...

    def draw_text(
        self, text: str, x: float, y: float, font_size: int, color: Color,
        *, font: FontHandle | None = None, anchor_x: str = "left", anchor_y: str = "baseline",
        space: Space = "screen", order: int = 0,
    ) -> None: ...

    def measure_text(
        self, text: str, font_size: int, font: FontHandle | None = None,
    ) -> tuple[int, int]:
        """Rendered ``(width, height)`` of *text* in logical pixels."""
        ...

    def load_font(self, name: str, path: str | None = None) -> FontHandle: ...

    # -- Audio ---------------------------------------------------------------

    def load_sound(self, path: str) -> SoundHandle:
        """Decode a short effect fully into memory; one handle plays any number of times."""
        ...

    def play_sound(self, handle: SoundHandle, volume: float = 1.0, pitch: float = 1.0) -> PlayerId:
        """Start an effect and return its opaque playback ID.

        The backend retains it until it ends or is stopped. *pitch* 1.0 is
        nominal; 2.0 plays an octave higher (and twice as fast), 0.5 lower.
        """
        ...

    def load_music(self, path: str) -> SoundHandle:
        """A streaming source; every call returns a fresh one (streams cannot be shared)."""
        ...

    def play_music(self, handle: SoundHandle, *, loop: bool = True, volume: float = 1.0) -> PlayerId: ...

    def set_player_volume(self, player_id: PlayerId, volume: float) -> None:
        """Set current gain; a player that has already ended stays ended."""
        ...

    def is_player_playing(self, player_id: PlayerId) -> bool:
        """Whether an effect or music player still has a source to play."""
        ...

    def stop_player(self, player_id: PlayerId) -> None:
        """Stop and release a player; safe on one whose source already ended."""
        ...

    def stop_sounds(self) -> None:
        """Stop and release every active sound effect, leaving music alone."""
        ...
