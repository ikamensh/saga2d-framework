"""Composable Actions — orchestrate multi-step sprite sequences.

Actions let game code express complex sprite behaviours as flat, readable
declarations instead of callback nesting or state machines::

    attacker.do(Sequence(
        Parallel(PlayAnim(walk), MoveTo(target_pos, speed=200)),
        PlayAnim(attack),
        Delay(0.3),
        Do(lambda: defender.do(PlayAnim(hit))),
        Parallel(PlayAnim(walk), MoveTo(original_pos, speed=200)),
        PlayAnim(idle),
        Do(on_complete),
    ))

    # Looping ambient
    torch.do(Repeat(Sequence(FadeOut(0.3), FadeIn(0.3), Delay(0.1))))

Every action follows the same protocol:

- ``start(sprite)`` — called once before the first ``update()``.
- ``update(dt) -> bool`` — called each frame; return ``True`` when done.
- ``stop()`` — called when cancelled (safe on unstarted actions).
"""

from __future__ import annotations

import copy
import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from saga2d.animation import AnimationDef
    from saga2d.rendering.sprite import Sprite


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class Action:
    """Base class for all composable actions."""

    @property
    def is_finite(self) -> bool:
        """Whether this action eventually completes.

        Defaults to ``True``.  Override for infinite actions (looping
        PlayAnim, forever Repeat) so that :class:`Parallel` knows to
        finish when all *finite* children are done — then ``stop()``
        the infinite ones.
        """
        return True

    def start(self, sprite: Sprite) -> None:
        """Called once when the action begins on *sprite*.

        Store the sprite reference for use during :meth:`update`.
        """

    def update(self, _dt: float) -> bool:
        """Advance by *_dt* seconds.  Return ``True`` when done.

        Called each frame by the sprite's action update loop.
        Return ``False`` while still running, ``True`` when complete.
        """
        return True

    def stop(self) -> None:
        """Called when cancelled (``sprite.stop_actions()`` or new ``do()``).

        Default no-op.  Override if clean-up is needed.  Implementations
        must handle ``stop()`` on an unstarted action gracefully (no-op).
        """


# ---------------------------------------------------------------------------
# Sequence
# ---------------------------------------------------------------------------


class Sequence(Action):
    """Run actions one after another.

    Instant actions (Do, Remove) chain within a single frame — a
    ``Sequence(Do(a), Do(b), Do(c))`` executes all three in one tick.
    """

    def __init__(self, *actions: Action) -> None:
        for i, action in enumerate(actions):
            if not isinstance(action, Action):
                raise TypeError(
                    f"Sequence child {i} is {type(action).__name__}, expected Action"
                )
        self._actions = list(actions)
        self._index = 0
        self._sprite: Sprite | None = None

    def start(self, sprite: Sprite) -> None:
        self._sprite = sprite
        if sprite is None:
            return
        if self._actions:
            self._actions[0].start(sprite)

    def update(self, dt: float) -> bool:
        if self._sprite is None:
            return True  # not started with a valid sprite
        while self._index < len(self._actions):
            child = self._actions[self._index]
            if child.update(dt):
                # Child finished — advance to the next.
                self._index += 1
                if self._index < len(self._actions):
                    self._actions[self._index].start(self._sprite)
                    dt = 0  # subsequently-started children get dt=0
                    continue
                else:
                    return True  # all done
            return False  # current child still running
        return True  # empty sequence

    def stop(self) -> None:
        if self._index < len(self._actions):
            self._actions[self._index].stop()


# ---------------------------------------------------------------------------
# Parallel
# ---------------------------------------------------------------------------


class Parallel(Action):
    """Run actions simultaneously.

    Finishes when all *finite* children are done, then calls ``stop()`` on
    any infinite children (e.g. looping ``PlayAnim``).  Two finite ``MoveTo``
    children correctly wait for the slower one.
    """

    def __init__(self, *actions: Action) -> None:
        for i, action in enumerate(actions):
            if not isinstance(action, Action):
                raise TypeError(
                    f"Parallel child {i} is {type(action).__name__}, expected Action"
                )
        self._actions = list(actions)
        self._done: list[bool] = [False] * len(actions)

    def start(self, sprite: Sprite) -> None:
        for action in self._actions:
            action.start(sprite)

    def update(self, dt: float) -> bool:
        for i, action in enumerate(self._actions):
            if not self._done[i]:
                if action.update(dt):
                    self._done[i] = True

        # Finished when every finite child is done.
        all_finite_done = all(
            self._done[i] or not action.is_finite
            for i, action in enumerate(self._actions)
        )

        if all_finite_done:
            # Stop any infinite children still running.
            for i, action in enumerate(self._actions):
                if not self._done[i]:
                    action.stop()
            return True

        return False

    def stop(self) -> None:
        for i, action in enumerate(self._actions):
            if not self._done[i]:
                action.stop()


# ---------------------------------------------------------------------------
# Delay
# ---------------------------------------------------------------------------


class Delay(Action):
    """Wait for *seconds*, then finish."""

    def __init__(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("seconds must be >= 0")
        self._seconds = seconds
        self._elapsed = 0.0

    def start(self, sprite: Sprite) -> None:
        pass

    def update(self, dt: float) -> bool:
        self._elapsed += dt
        return self._elapsed >= self._seconds


# ---------------------------------------------------------------------------
# Do
# ---------------------------------------------------------------------------


class Do(Action):
    """Call *fn* once, then finish immediately (instant action)."""

    def __init__(self, fn: Callable[[], Any]) -> None:
        self._fn = fn

    def start(self, sprite: Sprite) -> None:
        pass

    def update(self, _dt: float) -> bool:
        self._fn()
        return True


# ---------------------------------------------------------------------------
# PlayAnim
# ---------------------------------------------------------------------------


class PlayAnim(Action):
    """Play an animation on the sprite.

    For non-looping animations, finishes when the animation completes.
    For looping animations, ``is_finite`` is ``False`` — the action never
    finishes on its own.  Use inside :class:`Parallel` alongside a finite
    action; Parallel will ``stop()`` the PlayAnim when the finite actions
    complete.

    ``stop()`` calls ``sprite.stop_animation()`` to halt playback.
    """

    def __init__(self, anim_def: AnimationDef) -> None:
        self._anim_def = anim_def
        self._sprite: Sprite | None = None
        self._done = False

    @property
    def is_finite(self) -> bool:
        return not self._anim_def.loop

    def start(self, sprite: Sprite) -> None:
        self._sprite = sprite
        if self._anim_def.loop:
            sprite.play(self._anim_def)
        else:
            sprite.play(self._anim_def, on_complete=self._on_complete)

    def _on_complete(self) -> None:
        self._done = True

    def update(self, _dt: float) -> bool:
        return self._done

    def stop(self) -> None:
        if self._sprite is not None and not self._sprite.is_removed:
            self._sprite.stop_animation()


# ---------------------------------------------------------------------------
# MoveTo
# ---------------------------------------------------------------------------


class MoveTo(Action):
    """Move the sprite to *position* at *speed* pixels per second.

    Uses direct per-frame lerp (no tween system), so ``stop()`` is a
    no-op — the sprite stays wherever it is.
    """

    def __init__(self, position: tuple[float, float], speed: float) -> None:
        if speed <= 0:
            raise ValueError(f"speed must be > 0, got {speed}")
        x, y = float(position[0]), float(position[1])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError(
                f"target position must be finite floats, got ({position[0]!r}, {position[1]!r})"
            )
        self._target_x = x
        self._target_y = y
        self._speed = speed
        self._sprite: Sprite | None = None

    def start(self, sprite: Sprite) -> None:
        self._sprite = sprite

    def update(self, dt: float) -> bool:
        sprite = self._sprite
        if sprite is None:
            return True  # not started yet; treat as finished
        dx = self._target_x - sprite._x
        dy = self._target_y - sprite._y
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return True  # already there
        step = self._speed * dt
        if step >= dist:
            sprite.position = (self._target_x, self._target_y)
            return True  # arrived
        ratio = step / dist
        sprite.position = (sprite._x + dx * ratio, sprite._y + dy * ratio)
        return False

    def stop(self) -> None:
        pass  # leave sprite at current position


# ---------------------------------------------------------------------------
# FadeOut
# ---------------------------------------------------------------------------


class FadeOut(Action):
    """Fade opacity from current value to 0 over *duration* seconds."""

    def __init__(self, duration: float) -> None:
        self._duration = duration
        self._elapsed = 0.0
        self._start_opacity = 255
        self._sprite: Sprite | None = None

    def start(self, sprite: Sprite) -> None:
        self._sprite = sprite
        self._start_opacity = sprite.opacity

    def update(self, dt: float) -> bool:
        if self._sprite is None:
            return True  # not started yet; treat as finished
        self._elapsed += dt
        if self._elapsed >= self._duration:
            self._sprite.opacity = 0
            return True
        t = self._elapsed / self._duration
        self._sprite.opacity = int(self._start_opacity * (1.0 - t))
        return False

    def stop(self) -> None:
        pass  # leave opacity wherever it is


# ---------------------------------------------------------------------------
# FadeIn
# ---------------------------------------------------------------------------


class FadeIn(Action):
    """Fade opacity from current value to 255 over *duration* seconds."""

    def __init__(self, duration: float) -> None:
        self._duration = duration
        self._elapsed = 0.0
        self._start_opacity = 0
        self._sprite: Sprite | None = None

    def start(self, sprite: Sprite) -> None:
        self._sprite = sprite
        self._start_opacity = sprite.opacity

    def update(self, dt: float) -> bool:
        if self._sprite is None:
            return True  # not started yet; treat as finished
        self._elapsed += dt
        if self._elapsed >= self._duration:
            self._sprite.opacity = 255
            return True
        t = self._elapsed / self._duration
        self._sprite.opacity = int(
            self._start_opacity + (255 - self._start_opacity) * t
        )
        return False

    def stop(self) -> None:
        pass  # leave opacity wherever it is


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class Remove(Action):
    """Call ``sprite.remove()`` and finish immediately (instant action)."""

    def __init__(self) -> None:
        self._sprite: Sprite | None = None

    def start(self, sprite: Sprite) -> None:
        self._sprite = sprite

    def update(self, dt: float) -> bool:
        if self._sprite is None:
            return True  # not started yet; treat as finished
        self._sprite.remove()
        return True


# ---------------------------------------------------------------------------
# Repeat
# ---------------------------------------------------------------------------


class Repeat(Action):
    """Repeat *action* a fixed number of times, or forever.

    Each iteration uses a deep copy of the action template so that
    internal state (elapsed timers, etc.) starts fresh.

    Parameters:
        action: The action to repeat.
        times:  Number of repetitions.  ``None`` means infinite.
    """

    def __init__(self, action: Action, times: int | None = None) -> None:
        if not isinstance(action, Action):
            raise TypeError(
                f"Repeat child must be an Action, got {type(action).__name__}"
            )
        self._action_template = action
        self._times = times  # None = forever
        self._count = 0
        self._current: Action | None = None
        self._sprite: Sprite | None = None

    @property
    def is_finite(self) -> bool:
        return self._times is not None

    def start(self, sprite: Sprite) -> None:
        self._sprite = sprite
        if sprite is None:
            self._current = None
            return
        if self._times is not None and self._times <= 0:
            # Zero repetitions: no-op, finish immediately.
            self._current = None
            return
        self._current = copy.deepcopy(self._action_template)
        self._current.start(sprite)

    def update(self, dt: float) -> bool:
        if self._current is None:
            return True
        if self._current.update(dt):
            self._count += 1
            if self._times is not None and self._count >= self._times:
                return True  # done all repetitions
            # Start fresh copy for next iteration.
            self._current = copy.deepcopy(self._action_template)
            if self._sprite is not None:
                self._current.start(self._sprite)
        return False

    def stop(self) -> None:
        if self._current is not None:
            self._current.stop()
