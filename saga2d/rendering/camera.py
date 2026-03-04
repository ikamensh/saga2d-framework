"""Camera — pure-math viewport into a scrolling world.

The :class:`Camera` translates between world coordinates and screen (logical)
coordinates.  It supports centering, following a sprite, edge-scroll, manual
scroll, world-bounds clamping, and smooth ``pan_to()`` via the tween system.

**No backend dependency.** The camera is pure math — it produces an offset
that the rendering layer applies before sending positions to the backend.

Coordinate convention (y-down, top-left origin):

    screen_to_world(sx, sy) = (sx + camera.x, sy + camera.y)
    world_to_screen(wx, wy) = (wx - camera.x, wy - camera.y)

where ``camera.x``, ``camera.y`` is the top-left corner of the viewport in
world space.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from saga2d.util.tween import Ease

if TYPE_CHECKING:
    from saga2d.input import InputEvent
    from saga2d.rendering.sprite import Sprite


class Camera:
    """A 2D camera that maps a viewport onto a larger world.

    Parameters:
        viewport_size: ``(width, height)`` of the logical screen.
        world_bounds:  Optional ``(left, top, right, bottom)`` rectangle that
                       the camera is clamped inside.  ``None`` means no limits.
    """

    def __init__(
        self,
        viewport_size: tuple[int, int],
        *,
        world_bounds: tuple[float, float, float, float] | None = None,
    ) -> None:
        self._vw: int = viewport_size[0]
        self._vh: int = viewport_size[1]

        # Top-left corner of the viewport in world space.
        self._x: float = 0.0
        self._y: float = 0.0

        # Optional world-bounds clamping: (left, top, right, bottom).
        self._world_bounds = world_bounds

        # Follow mode.
        self._follow_target: Sprite | None = None

        # Edge scroll.
        self._edge_scroll_enabled: bool = False
        self._edge_margin: int = 0
        self._edge_speed: float = 0.0

        # Key scroll (arrow keys).
        self._key_scroll_enabled: bool = False
        self._key_scroll_speed: float = 0.0
        self._held_dirs: set[str] = set()  # "left", "right", "up", "down"

        # Pan-to tween ids (so we can cancel on follow / center_on / scroll).
        self._pan_tween_x: int | None = None
        self._pan_tween_y: int | None = None
        self._tween_manager: Any = None  # set by pan_to() from Game's manager

        # Shake effect.
        self._shake_intensity: float = 0.0
        self._shake_duration: float = 0.0
        self._shake_elapsed: float = 0.0
        self._shake_decay: float = 1.0
        self._shake_offset_x: float = 0.0
        self._shake_offset_y: float = 0.0

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def x(self) -> float:
        """Top-left x of the viewport in world space (read-only)."""
        return self._x

    @property
    def y(self) -> float:
        """Top-left y of the viewport in world space (read-only)."""
        return self._y

    @property
    def viewport_width(self) -> int:
        return self._vw

    @property
    def viewport_height(self) -> int:
        return self._vh

    @property
    def shake_offset_x(self) -> float:
        """Current horizontal shake offset in pixels (read-only)."""
        return self._shake_offset_x

    @property
    def shake_offset_y(self) -> float:
        """Current vertical shake offset in pixels (read-only)."""
        return self._shake_offset_y

    @property
    def world_bounds(self) -> tuple[float, float, float, float] | None:
        return self._world_bounds

    @world_bounds.setter
    def world_bounds(
        self,
        value: tuple[float, float, float, float] | None,
    ) -> None:
        self._world_bounds = value
        self._clamp()

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def center_on(self, x: float, y: float) -> None:
        """Center the viewport on world position ``(x, y)``.

        Cancels any active pan and disables follow.

        Raises:
            ValueError: If *x* or *y* is NaN or Inf.
        """
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(
                f"camera coordinates must be finite (not NaN or Inf), got ({x}, {y})"
            )
        self._cancel_pan()
        self._follow_target = None
        self._x = x - self._vw / 2
        self._y = y - self._vh / 2
        self._clamp()

    def follow(self, sprite: Sprite | None) -> None:
        """Follow *sprite* each frame (center on its position).

        Cancels any active pan.  Pass ``None`` to stop following.
        """
        self._cancel_pan()
        self._follow_target = sprite

    def scroll(self, dx: float, dy: float) -> None:
        """Manually scroll the camera by ``(dx, dy)`` pixels.

        Cancels any active pan and disables follow.
        """
        self._cancel_pan()
        self._follow_target = None
        self._x += dx
        self._y += dy
        self._clamp()

    # ------------------------------------------------------------------
    # Edge scroll
    # ------------------------------------------------------------------

    def enable_edge_scroll(self, margin: int, speed: float) -> None:
        """Enable edge scrolling.

        When the mouse is within *margin* pixels of the viewport edge,
        the camera scrolls at *speed* pixels per second toward that edge.
        """
        self._edge_scroll_enabled = True
        self._edge_margin = margin
        self._edge_speed = speed

    def disable_edge_scroll(self) -> None:
        """Disable edge scrolling."""
        self._edge_scroll_enabled = False

    # ------------------------------------------------------------------
    # Key scroll
    # ------------------------------------------------------------------

    def enable_key_scroll(self, speed: float = 300) -> None:
        """Enable arrow-key scrolling.

        When arrow keys are held, the camera scrolls at *speed* pixels per
        second.  Tracks key_press/key_release internally; call
        :meth:`handle_input` from the game loop (the framework does this
        automatically when the scene has a camera).
        """
        self._key_scroll_enabled = True
        self._key_scroll_speed = speed

    def disable_key_scroll(self) -> None:
        """Disable arrow-key scrolling."""
        self._key_scroll_enabled = False
        self._held_dirs.clear()

    def handle_input(self, event: InputEvent) -> bool:
        """Process directional key events for key scroll.

        Called by :meth:`Game.tick` before scene dispatch when the scene
        has a camera.  Returns ``True`` if the event was consumed (a
        directional key_press/key_release), ``False`` otherwise.
        """
        if not self._key_scroll_enabled:
            return False
        if event.type not in ("key_press", "key_release"):
            return False
        action = getattr(event, "action", None)
        if action not in ("left", "right", "up", "down"):
            return False
        if event.type == "key_press":
            self._held_dirs.add(action)
        else:
            self._held_dirs.discard(action)
        return True

    # ------------------------------------------------------------------
    # Shake
    # ------------------------------------------------------------------

    def shake(self, intensity: float, duration: float, decay: float) -> None:
        """Start a screen-shake effect.

        The camera offsets are updated each frame in :meth:`update` with
        random values whose magnitude decays over *duration* seconds.

        Parameters:
            intensity: Maximum pixel offset at the start of the shake.
            duration:  How long (seconds) the shake lasts.  A duration of
                       ``0`` is a no-op that immediately resets any active
                       shake.
            decay:     Exponent applied to the linear progress
                       ``(1 - elapsed/duration)**decay`` — higher values
                       make the shake die out faster.
        """
        if duration <= 0:
            # Treat zero/negative duration as a reset.
            self._shake_intensity = 0.0
            self._shake_duration = 0.0
            self._shake_elapsed = 0.0
            self._shake_decay = 1.0
            self._shake_offset_x = 0.0
            self._shake_offset_y = 0.0
            return

        self._shake_intensity = intensity
        self._shake_duration = duration
        self._shake_elapsed = 0.0
        self._shake_decay = decay
        self._shake_offset_x = 0.0
        self._shake_offset_y = 0.0

    # ------------------------------------------------------------------
    # Coordinate conversion
    # ------------------------------------------------------------------

    def screen_to_world(
        self,
        sx: float,
        sy: float,
    ) -> tuple[float, float]:
        """Convert screen (logical) coordinates to world coordinates."""
        return (sx + self._x, sy + self._y)

    def world_to_screen(
        self,
        wx: float,
        wy: float,
    ) -> tuple[float, float]:
        """Convert world coordinates to screen (logical) coordinates."""
        return (wx - self._x, wy - self._y)

    # ------------------------------------------------------------------
    # Smooth pan
    # ------------------------------------------------------------------

    def pan_to(
        self,
        x: float,
        y: float,
        duration: float,
        ease: Ease | None = None,
    ) -> None:
        """Smoothly pan the viewport center to ``(x, y)`` over *duration* seconds.

        Uses the existing tween system.  Disables follow.  If a pan is already
        active it is cancelled first.

        Parameters:
            x:        Target world x to center on.
            y:        Target world y to center on.
            duration: Seconds for the pan animation.
            ease:     An :class:`~easygame.util.tween.Ease` value (default
                      ``Ease.EASE_IN_OUT``).
        """
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"pan_to requires finite x and y, got ({x}, {y})")
        from saga2d.util import tween as tween_mod
        from saga2d.util.tween import Ease, tween

        # Capture the instance tween manager so _cancel_pan doesn't rely on
        # the module-level global (which may point to a different Game).
        self._tween_manager = tween_mod._tween_manager

        self._cancel_pan()
        self._follow_target = None

        if ease is None:
            ease = Ease.EASE_IN_OUT

        # Target top-left so that (x, y) is centered.
        target_x = x - self._vw / 2
        target_y = y - self._vh / 2

        # Clamp target the same way _clamp() would.
        if self._world_bounds is not None:
            left, top, right, bottom = self._world_bounds
            target_x = max(left, min(target_x, right - self._vw))
            target_y = max(top, min(target_y, bottom - self._vh))

        self._pan_tween_x = tween(
            self,
            "_x",
            self._x,
            target_x,
            duration,
            ease=ease,
        )
        self._pan_tween_y = tween(
            self,
            "_y",
            self._y,
            target_y,
            duration,
            ease=ease,
            on_complete=self._on_pan_complete,
        )

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(
        self,
        dt: float,
        mouse_x: float | None = None,
        mouse_y: float | None = None,
    ) -> None:
        """Advance per-frame camera logic.

        Called once per frame by :meth:`Game.tick` before the render-sync pass.

        Handles:
        1. Follow tracking — center on the followed sprite.
        2. Edge scroll — scroll when the mouse is near a viewport edge.
        3. Key scroll — scroll when arrow keys are held.
        4. Shake effect — apply decaying random offset from :meth:`shake`.

        Parameters:
            dt:      Delta time in seconds.
            mouse_x: Current mouse x in logical screen coordinates (or ``None``).
            mouse_y: Current mouse y in logical screen coordinates (or ``None``).
        """
        # 1. Follow tracking.
        if self._follow_target is not None:
            target = self._follow_target
            # Guard against removed sprites.
            if hasattr(target, "is_removed") and target.is_removed:
                self._follow_target = None
            else:
                self._x = target.x - self._vw / 2
                self._y = target.y - self._vh / 2
                self._clamp()

        # 2. Edge scroll.
        if self._edge_scroll_enabled and mouse_x is not None and mouse_y is not None:
            scroll_dx = 0.0
            scroll_dy = 0.0
            margin = self._edge_margin
            speed = self._edge_speed

            if mouse_x < margin:
                scroll_dx = -speed * dt
            elif mouse_x > self._vw - margin:
                scroll_dx = speed * dt

            if mouse_y < margin:
                scroll_dy = -speed * dt
            elif mouse_y > self._vh - margin:
                scroll_dy = speed * dt

            if scroll_dx != 0.0 or scroll_dy != 0.0:
                self._x += scroll_dx
                self._y += scroll_dy
                self._clamp()

        # 3. Key scroll.
        if self._key_scroll_enabled and self._held_dirs:
            speed = self._key_scroll_speed * dt
            scroll_dx = (-speed if "left" in self._held_dirs else 0) + (
                speed if "right" in self._held_dirs else 0
            )
            scroll_dy = (-speed if "up" in self._held_dirs else 0) + (
                speed if "down" in self._held_dirs else 0
            )
            if scroll_dx != 0.0 or scroll_dy != 0.0:
                self._x += scroll_dx
                self._y += scroll_dy
                self._clamp()

        # 4. Shake effect.
        if self._shake_duration > 0.0 and self._shake_elapsed < self._shake_duration:
            self._shake_elapsed += dt
            if self._shake_elapsed >= self._shake_duration:
                # Shake finished.
                self._shake_offset_x = 0.0
                self._shake_offset_y = 0.0
                self._shake_duration = 0.0
            else:
                progress = self._shake_elapsed / self._shake_duration
                decayed_intensity = (
                    self._shake_intensity * (1.0 - progress) ** self._shake_decay
                )
                self._shake_offset_x = random.uniform(
                    -decayed_intensity, decayed_intensity
                )
                self._shake_offset_y = random.uniform(
                    -decayed_intensity, decayed_intensity
                )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _clamp(self) -> None:
        """Clamp ``(_x, _y)`` so the viewport stays inside world_bounds."""
        if self._world_bounds is None:
            return
        left, top, right, bottom = self._world_bounds
        # Maximum top-left so bottom-right of viewport doesn't exceed bounds.
        max_x = right - self._vw
        max_y = bottom - self._vh
        self._x = max(left, min(self._x, max_x))
        self._y = max(top, min(self._y, max_y))

    def _cancel_pan(self) -> None:
        """Cancel any active pan tweens."""
        mgr = self._tween_manager
        if mgr is not None:
            if self._pan_tween_x is not None:
                mgr.cancel(self._pan_tween_x)
                self._pan_tween_x = None
            if self._pan_tween_y is not None:
                mgr.cancel(self._pan_tween_y)
                self._pan_tween_y = None
        else:
            # No tween manager yet (during tests or before Game init) — just clear ids.
            self._pan_tween_x = None
            self._pan_tween_y = None

    def _on_pan_complete(self) -> None:
        """Called when a pan_to animation finishes."""
        self._pan_tween_x = None
        self._pan_tween_y = None
        self._clamp()
