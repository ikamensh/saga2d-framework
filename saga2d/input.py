"""Raw backend events → :class:`InputEvent`, plus held-key state.

Keys are plain lowercase names (``"a"``, ``"space"``, ``"escape"``,
``"return"``, ``"tab"``, ``"up"``…).  :func:`key_combo` renders an event
as ``"ctrl+shift+s"`` so :attr:`Scene.controls` can bind modifier chords.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from saga2d.backends.base import Event, KeyEvent, MouseEvent

if TYPE_CHECKING:
    from saga2d.rendering.camera import Camera

_MODIFIER_KEYS = frozenset({"lshift", "rshift", "lctrl", "rctrl", "lalt", "ralt", "loption", "roption", "lcommand", "rcommand", "lmeta", "rmeta", "lwindows", "rwindows"})


@dataclass(frozen=True)
class InputEvent:
    """A keyboard or mouse event.

    Keyboard: ``type`` is ``"key_press"``/``"key_release"``, ``key`` is set.
    Mouse: ``type`` is ``"click"``/``"release"``/``"move"``/``"drag"``/
    ``"scroll"``; ``x``/``y`` are logical screen coordinates and
    ``world_x``/``world_y`` the camera-transformed position (equal to
    ``x``/``y`` when the scene has no camera).
    """

    type: str
    key: str | None = None
    x: int = 0
    y: int = 0
    button: str | None = None
    dx: int = 0
    dy: int = 0
    world_x: float | None = None
    world_y: float | None = None
    shift: bool = False
    ctrl: bool = False
    alt: bool = False
    meta: bool = False

    @property
    def is_mouse(self) -> bool:
        return self.key is None

    @property
    def combo(self) -> str | None:
        """``"ctrl+shift+s"``-style name for keyboard events, else ``None``."""
        if self.key is None:
            return None
        return key_combo(self.key, ctrl=self.ctrl, alt=self.alt, shift=self.shift, meta=self.meta)


def key_combo(key: str, *, ctrl: bool = False, alt: bool = False, shift: bool = False, meta: bool = False) -> str:
    parts = []
    if ctrl:
        parts.append("ctrl")
    if alt:
        parts.append("alt")
    if shift:
        parts.append("shift")
    if meta:
        parts.append("meta")
    parts.append(key)
    return "+".join(parts)


def normalize_combo(combo: str) -> str:
    """Canonical modifier order for a user-written chord like ``"shift+ctrl+s"``."""
    parts = [p.strip().lower() for p in combo.split("+")]
    key = parts[-1]
    mods = set(parts[:-1])
    unknown = mods - {"ctrl", "alt", "shift", "meta"}
    if unknown:
        raise ValueError(f"unknown modifier(s) {sorted(unknown)} in key combo {combo!r}")
    return key_combo(key, ctrl="ctrl" in mods, alt="alt" in mods, shift="shift" in mods, meta="meta" in mods)


def with_world_coords(event: InputEvent, camera: Camera | None) -> InputEvent:
    if not event.is_mouse:
        return event
    if camera is not None:
        wx, wy = camera.screen_to_world(event.x, event.y)
    else:
        wx, wy = float(event.x), float(event.y)
    return replace(event, world_x=wx, world_y=wy)


class InputManager:
    """Translates backend events and tracks which keys are held."""

    def __init__(self) -> None:
        self._pressed: set[str] = set()

    def is_pressed(self, key: str) -> bool:
        return key in self._pressed

    def pressed_keys(self) -> frozenset[str]:
        return frozenset(self._pressed)

    def release_all(self) -> None:
        self._pressed.clear()

    def translate(self, raw_events: list[Event]) -> list[InputEvent]:
        result: list[InputEvent] = []
        for event in raw_events:
            if isinstance(event, KeyEvent):
                if event.type == "key_press":
                    self._pressed.add(event.key)
                elif event.type == "key_release":
                    self._pressed.discard(event.key)
                if event.key in _MODIFIER_KEYS:
                    continue
                result.append(InputEvent(
                    type=event.type, key=event.key,
                    shift=event.shift, ctrl=event.ctrl, alt=event.alt, meta=event.meta,
                ))
            elif isinstance(event, MouseEvent):
                result.append(InputEvent(
                    type=event.type, x=event.x, y=event.y, button=event.button, dx=event.dx, dy=event.dy,
                ))
        return result
