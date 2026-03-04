"""Input translation layer: raw backend events → action-mapped InputEvents.

:class:`InputEvent` is a frozen dataclass that unifies keyboard and mouse
events with an optional ``action`` field.  The ``action`` is populated by
:class:`InputManager`, which maintains a configurable key→action mapping.

Game code checks ``event.action`` for intent-based input::

    def handle_input(self, event: InputEvent) -> bool:
        if event.action == "confirm":
            self.select_current()
            return True

The ``InputManager`` is owned by :class:`~saga2d.game.Game` and exposed
as ``game.input``.  It provides default bindings for common actions (confirm,
cancel, directional) and supports rebinding at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from saga2d.backends.base import Event, KeyEvent, MouseEvent

if TYPE_CHECKING:
    from saga2d.rendering.camera import Camera


# ---------------------------------------------------------------------------
# InputEvent — frozen dataclass, public
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputEvent:
    """Translated input event with optional action mapping.

    For keyboard events::

        type: "key_press" | "key_release"
        key: raw key string (e.g. "a", "space", "return")
        action: mapped action (e.g. "confirm", "attack") or None

    For mouse events::

        type: "click" | "release" | "move" | "drag" | "scroll"
        x, y: logical coordinates (already converted by backend)
        button: "left" | "right" | "middle" | None
        dx, dy: drag/scroll deltas
        action: None (mouse events don't map to actions)
        world_x, world_y: camera-transformed coordinates (auto-populated)

    Attributes:
        type:     Event type string.
        key:      Raw key name for keyboard events, ``None`` for mouse.
        action:   Mapped action name, or ``None`` if no binding exists.
        x:        Logical x coordinate (mouse events).
        y:        Logical y coordinate (mouse events).
        button:   Mouse button name, or ``None``.
        dx:       Horizontal delta (drag/scroll).
        dy:       Vertical delta (drag/scroll).
        world_x:  Camera-transformed x coordinate, or ``None`` for non-mouse
                  events.  Populated automatically by the framework before
                  the event reaches :meth:`Scene.handle_input`.  When the
                  scene has a camera, equals ``camera.screen_to_world(x, y)[0]``.
                  When there is no camera, equals ``x``.
        world_y:  Camera-transformed y coordinate (see *world_x*).
    """

    type: str
    key: str | None = None
    action: str | None = None
    x: int = 0
    y: int = 0
    button: str | None = None
    dx: int = 0
    dy: int = 0
    world_x: float | None = None
    world_y: float | None = None


# Mouse event types that carry meaningful coordinates.
_MOUSE_EVENT_TYPES = frozenset({"click", "release", "move", "drag", "scroll"})


def _with_world_coords(
    event: InputEvent,
    camera: Camera | None,
) -> InputEvent:
    """Return *event* with ``world_x``/``world_y`` populated.

    * **Mouse events** — if *camera* is not ``None``, world coordinates are
      computed via ``camera.screen_to_world(event.x, event.y)``.  If *camera*
      is ``None`` (UI-only scene), world coordinates equal screen coordinates.
    * **Non-mouse events** — returned unchanged (``world_x``/``world_y`` stay
      ``None``).

    This is called by :meth:`Game.tick` before dispatching to scenes so that
    game code never needs to call ``camera.screen_to_world`` manually.
    """
    if event.type not in _MOUSE_EVENT_TYPES:
        return event
    if camera is not None:
        wx, wy = camera.screen_to_world(event.x, event.y)
    else:
        wx = float(event.x)
        wy = float(event.y)
    return replace(event, world_x=wx, world_y=wy)


# ---------------------------------------------------------------------------
# InputManager — internal, accessed via game.input
# ---------------------------------------------------------------------------


class InputManager:
    """Translates raw backend events into :class:`InputEvent` objects.

    Maintains a bidirectional key↔action mapping.  Each action maps to
    exactly one key; binding a new key to an existing action replaces the
    old binding.  Binding a key that is already bound to a *different*
    action steals it (unbinds the old action first).

    Currently only one key can be bound to one action (1:1 mapping).
    Multi-key support may be added in a future version if needed.

    Default bindings::

        confirm → return
        cancel  → escape
        up      → up
        down    → down
        left    → left
        right   → right
    """

    def __init__(self) -> None:
        self._key_to_action: dict[str, str] = {}
        self._action_to_key: dict[str, str] = {}
        self._setup_defaults()

    # ------------------------------------------------------------------
    # Binding API
    # ------------------------------------------------------------------

    def bind(self, action: str, key: str) -> None:
        """Bind *action* to *key*.

        If *action* was already bound to a different key, the old binding
        is removed.  If *key* was already bound to a different action, that
        action is unbound first (key stealing).
        """
        # Remove old key for this action (if any).
        old_key = self._action_to_key.pop(action, None)
        if old_key is not None:
            self._key_to_action.pop(old_key, None)

        # Steal key from any other action that had it.
        old_action = self._key_to_action.pop(key, None)
        if old_action is not None:
            self._action_to_key.pop(old_action, None)

        self._key_to_action[key] = action
        self._action_to_key[action] = key

    def unbind(self, action: str) -> None:
        """Remove the binding for *action*.  No-op if not bound."""
        key = self._action_to_key.pop(action, None)
        if key is not None:
            self._key_to_action.pop(key, None)

    def get_bindings(self) -> dict[str, str]:
        """Return a copy of the current action→key mapping."""
        return dict(self._action_to_key)

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    def translate(self, raw_events: list[Event] | None) -> list[InputEvent]:
        """Translate a list of raw backend events into :class:`InputEvent` s.

        :class:`WindowEvent` objects are **not** translated — they are
        handled by the framework before this method is called and should
        not appear in *raw_events*.

        If *raw_events* is ``None``, returns ``[]``.
        """
        if raw_events is None:
            return []
        result: list[InputEvent] = []
        for event in raw_events:
            if isinstance(event, KeyEvent):
                action = self._key_to_action.get(event.key)
                result.append(
                    InputEvent(
                        type=event.type,
                        key=event.key,
                        action=action,
                    )
                )
            elif isinstance(event, MouseEvent):
                result.append(
                    InputEvent(
                        type=event.type,
                        x=event.x,
                        y=event.y,
                        button=event.button,
                        dx=event.dx,
                        dy=event.dy,
                    )
                )
            # WindowEvent is intentionally skipped — handled by Game.tick().
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _setup_defaults(self) -> None:
        """Install the default action bindings."""
        self.bind("confirm", "return")
        self.bind("cancel", "escape")
        self.bind("up", "up")
        self.bind("down", "down")
        self.bind("left", "left")
        self.bind("right", "right")
